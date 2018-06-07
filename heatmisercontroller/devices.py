#
# Ian Horsley 2018

#
# hmController class
# handles all the DCB and data objects for each controller on the heatmiser network

# Assume Python 2.7.x
#

#consider adding timestamps to all parameters for their age.
#relook at the setfield and setfields. Should they be in adaptor. Payload length checking should happen on all results.
#some sort of get variable function, with max age, for single parameters. if to old would autoget. Still need to auto trigger full read in some cases.

import logging
import time
import serial
from datetime import datetime

from hm_constants import *
from .exceptions import hmResponseError, hmControllerTimeError
from schedule_functions import schedulerdayheat, schedulerweekheat, schedulerdaywater, schedulerweekwater, SCH_ENT_TEMP

class hmController(object):

  def __init__(self, network, address, protocol, short_name, long_name, model, mode):
    self.network = network
    self.address = address
    self.protocol = protocol
    self.expected_model = model
    self.expected_prog_mode = mode
    
    self.water_schedule = None
    if self.expected_prog_mode == PROG_MODE_DAY:
      self.heat_schedule = schedulerdayheat()
      if model == PRT_HW_MODEL:
        self.water_schedule = schedulerdaywater()
    elif self.expected_prog_mode == PROG_MODE_WEEK:
      self.heat_schedule = schedulerweekheat()
      if model == PRT_HW_MODEL:
        self.water_schedule = schedulerweekwater()
    else:
      raise ValueError("Unknown program mode")
      
    if model == PRT_E_MODEL:
      self.DCBmap = PRTEmap[mode]
    elif model == PRT_HW_MODEL:
      self.DCBmap = PRTHWmap[mode]
    elif model == False:
      self.DCBmap = STRAIGHTmap
    else:
      raise ValueError("UNKNOWN MODEL")
      
    if self.DCBmap[0][1] != DCB_INVALID:
      self.DCBlength = self.DCBmap[0][0] - self.DCBmap[0][1] + 1
    elif self.DCBmap[1][1] != DCB_INVALID:
      self.DCBlength = self.DCBmap[1][0] - self.DCBmap[1][1] + 1
    else:
      raise ValueError("DCB map length not found")
    
    self.rawdata = [None] * self.DCBlength
    
    self.name = short_name
    self.long_name = long_name
    
    self.lastreadtime = 0 #records last time of a successful read
    
    #initialise data structures
    self.data = dict.fromkeys(uniadd.keys(),None)
    self.datareadtime = dict.fromkeys(uniadd.keys(),None)
    
    ###SHOULD BE TRUE
    self.autoreadall = True
   
  def _getDCBaddress(self, uniqueaddress):
    #get the DCB address for a controller from the unique address

    offset = DCB_INVALID
    for uniquemax, offsetsel in self.DCBmap:
      if uniqueaddress <= uniquemax:
        offset = offsetsel
    
    if offset != DCB_INVALID:
      return uniqueaddress-offset
    else:
      return DCB_INVALID
      
  def getRawData(self, startfieldname = None, endfieldname = None):
    if startfieldname == None or endfieldname == None:
      return self.rawdata
    else:
      return self.rawdata[self._getDCBaddress(uniadd[startfieldname][UNIADD_ADD]):self._getDCBaddress(uniadd[endfieldname][UNIADD_ADD])]
    
  def hmReadVariables(self):
    rawdata1 = self.hmReadFields('setroomtemp', 'holidayhours')
  
    if self.readField('model', None) == PRT_HW_MODEL:
      lastfield = 'hotwaterstate'
    else:
      lastfield = 'heatingstate'

    rawdata2 = self.hmReadFields('tempholdmins', lastfield)
    
    return rawdata1 + rawdata2
    
  def hmReadTempsandDemand(self):
  
    if self.readField('model', None) == PRT_HW_MODEL:
      lastfield = 'hotwaterstate'
    else:
      lastfield = 'heatingstate'

    rawdata = self.hmReadFields('remoteairtemp', lastfield)

    return rawdata
    
  def readTime(self, maxage = 0):
    return self.readField('currenttime', maxage)

  def hmReadAll(self):
    try:
      self.rawdata = self.network.hmReadAllFromController(self.address, self.protocol, self.DCBlength)
    except serial.SerialException as e:
      logging.warn("C%i Read all failed, Serial Port error %s"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH), str(e)))
      raise
    else:
      logging.info("C%i Read all, %s"%(self.address, ', '.join(str(x) for x in self.rawdata)))
      self.lastreadtime = time.time()
      self._procpayload(self.rawdata)
      return self.rawdata

  def readField(self, fieldname, maxage = 0):
    #return field value
    #read field from network if
    # no maxage in request (maxage = 0)
    # maxage is valid and data too old
    # or not be read before (maxage = None)
    if maxage == 0 or (maxage is not None and self._check_data_age(maxage, fieldname)) or not self._check_data_present(fieldname):
      if self.autoreadall:
        self.hmReadFields(fieldname)
      else:
        raise ValueError("Need to read %s first"%fieldname)
    return self.data[fieldname]
  
  #consider moving to adaptor.py
  def hmReadFields(self, firstfieldname, lastfieldname = None):
    if lastfieldname == None:
      lastfieldname = firstfieldname
  
    firstfieldinfo = uniadd[firstfieldname]
    lastfieldinfo = uniadd[lastfieldname]

    readlength = lastfieldinfo[UNIADD_ADD] - firstfieldinfo[UNIADD_ADD] + lastfieldinfo[UNIADD_LEN]

    try:
      rawdata = self.network.hmReadFromController(self.address, self.protocol, firstfieldinfo[UNIADD_ADD], readlength)
    except serial.SerialException as e:
      logging.warn("C%i Read failed of fields %s to %s, Serial Port error %s"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH), str(e)))
      raise
    else:
      logging.info("C%i Read fields %s to %s, %s"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH), ', '.join(str(x) for x in rawdata)))
      self.lastreadtime = time.time()
      self._procpartpayload(rawdata, firstfieldname, lastfieldname)
      return rawdata
  
  def _procfield(self,data,fieldname,fieldinfo):
    length = fieldinfo[UNIADD_LEN]
    factor = fieldinfo[UNIADD_DIV]
    range = fieldinfo[UNIADD_RANGE]
  
    if length == 1:
      value = data[0]/factor
    elif length == 2:
      val_high = data[0]
      val_low  = data[1]
      value = 1.0*(val_high*256 + val_low)/factor #force float, although always returns integer temps.
    elif length == 4:
      value = data
    elif length == 12:
      self.heat_schedule.set_raw(fieldname,data)
      value = data
    elif length == 16:
      self.water_schedule.set_raw(fieldname,data)
      value = data
    else:
      raise ValueError("_procpayload can't process field length")
  
    if len(range) == 2 and isinstance(range[0], (int, long)) and isinstance(range[1], (int, long)):
      if value < range[0] or value > range[1]:
        raise hmResponseError("Field value %i outside expected range"%value)
    
    if fieldname == 'DCBlen' and value != self.DCBlength:
      raise hmResponseError('DCBlengh is unexpected')
    
    if fieldname == 'model' and value != self.expected_model:
      raise hmResponseError('Model is unexpected')
    
    if fieldname == 'programmode' and value != self.expected_prog_mode:
      raise hmResponseError('Programme mode is unexpected')
    
    if fieldname == 'version' and self.expected_model != PRT_HW_MODEL:
      value = data[0] & 0x7f
      self.floorlimiting = data[0] >> 7
      self.data['floorlimiting'] = self.floorlimiting
    
    self.data[fieldname] = value
    setattr(self, fieldname, value)
    self.datareadtime[fieldname] = self.lastreadtime
    
    if fieldname == 'currenttime':
      self._checkcontrollertime(self.lastreadtime)
    
    ###todo, add range validation for other lengths

  def _procpartpayload(self, rawdata, firstfieldname, lastfieldname):
    #converts field names to unique addresses to allow process of shortened raw data
    firstfieldadd = uniadd[firstfieldname][UNIADD_ADD] 
    lastfieldadd = uniadd[lastfieldname][UNIADD_ADD]
    self._procpayload(rawdata, firstfieldadd, lastfieldadd)
    
  def _procpayload(self, rawdata, firstfieldadd = 0, lastfieldadd = MAX_UNIQUE_ADDRESS):
    logging.debug("C%i Processing Payload"%(self.address) )

    fullfirstdcbadd = self._getDCBaddress(firstfieldadd)
    
    for attrname, values in uniadd.iteritems():
      uniqueaddress = values[UNIADD_ADD]
      if uniqueaddress >= firstfieldadd and uniqueaddress <= lastfieldadd:
        length = values[UNIADD_LEN]

        ###todo, add 7 day prog to getDCBaddress selection
        dcbadd = self._getDCBaddress(uniqueaddress)

        if dcbadd == DCB_INVALID:
          setattr(self, attrname, None)
        else:
          dcbadd -= fullfirstdcbadd #adjust for the start of the request
          
          try:
            self._procfield(rawdata[dcbadd:dcbadd+length], attrname, values)
          except hmResponseError as e:
            logging.warn("C%i Field %s process failed due to %s"%(self.address, attrname, str(e)))

    self.rawdata[fullfirstdcbadd:fullfirstdcbadd+len(rawdata)] = rawdata

  def _checkcontrollertime(self,checktime):       
    # Now do same sanity checking
    # Check the time is within range
    # If we only do this at say 1 am then there is no issues/complication of day wrap rounds
    # TODO only do once a day
    # currentday is numbered 1-7 for M-S
    # localday (python) is numbered 0-6 for Sun-Sat

    localtime = time.localtime(checktime)
    if not self._check_data_present('currenttime'):
      raise hmResponseError("Time not read before check")
    
    localday = time.strftime("%w", localtime)
    
    remoteday = self.currenttime[CURRENT_TIME_DAY]%7
    if (int(localday) != int(remoteday)):
        raise hmControllerTimeError("C%2d Incorrect day : local is %s, sensor is %s" % (self.address, localday, remoteday))

    remoteseconds = (((self.currenttime[CURRENT_TIME_HOUR] * 60) + self.currenttime[CURRENT_TIME_MIN]) * 60) + self.currenttime[CURRENT_TIME_SEC]

    nowhours = localtime.tm_hour
    nowmins = localtime.tm_min
    nowsecs = localtime.tm_sec
    nowseconds = (((nowhours * 60) + nowmins) * 60) + nowsecs
    logging.debug("Time %d %d" % (remoteseconds, nowseconds))
    self.timeerr = nowseconds - remoteseconds
    if (abs(self.timeerr) > TIME_ERR_LIMIT):
        raise hmControllerTimeError("C%2d Time Error : Greater than %d local is %s, sensor is %s" % (self.address, TIME_ERR_LIMIT, nowseconds, remoteseconds))

  TEMP_STATE_OFF = 0  #thermostat display is off and frost protection disabled
  TEMP_STATE_OFF_FROST = 1 #thermostat display is off and frost protection enabled
  TEMP_STATE_FROST = 2 #frost protection enabled indefinitely
  TEMP_STATE_HOLIDAY = 3 #holiday mode, frost protection for a period
  TEMP_STATE_HELD = 4 #temperature held for a number of hours
  TEMP_STATE_OVERRIDDEN = 5 #temperature overridden until next program time
  TEMP_STATE_PROGRAM = 6 #following program
  
  def getTempState(self):
    if not self._check_data_present('onoff','frostprot','holidayhours','runmode','tempholdmins','setroomtemp'):
      if self.autoreadall:
        self.hmReadAll()
      else:
        raise ValueError("Need to read all before getting temp state")
        
    if not self._check_data_age(60, 'onoff','holidayhours','runmode','tempholdmins','setroomtemp'):
      if self.autoreadall:
        self.hmReadVariables()
      else:
        raise ValueError("Vars to old to get temp state")
    
    if self.onoff == WRITE_ONOFF_OFF and self.frostprot == READ_FROST_PROT_OFF:
      return self.TEMP_STATE_OFF
    elif self.onoff == WRITE_ONOFF_OFF and self.frostprot == READ_FROST_PROT_ON:
      return self.TEMP_STATE_OFF_FROST
    elif self.holidayhours != 0:
      return self.TEMP_STATE_HOLIDAY
    elif self.runmode == WRITE_RUNMODE_FROST:
      return self.TEMP_STATE_FROST
    elif self.tempholdmins != 0:
      return self.TEMP_STATE_HELD
    else:
    
      if not self._check_data_age(60 * 60 * 2, 'currenttime'):
        currenttime = self.hmReadTime()
        self._checkcontrollertime(self.lastreadtimetime)
      
      locatimenow = self._localtimearray()
      scheduletarget = self.heat_schedule.getCurrentScheduleItem(locatimenow)

      if scheduletarget[SCH_ENT_TEMP] != self.setroomtemp:
        return self.TEMP_STATE_OVERRIDDEN
      else:
        return self.TEMP_STATE_PROGRAM
  
  def _localtimearray(self, timenow = time.time()):
    #creates an array in heatmiser format for local time. Day 1-7, 1=Monday
    #input time.time() (not local)
    localtimenow = time.localtime(timenow)
    nowday = localtimenow.tm_wday + 1  #python tm_wday, range [0, 6], Monday is 0
    nowsecs = min(localtimenow.tm_sec, 59) #python tm_sec range[0, 61]
    
    return [nowday, localtimenow.tm_hour, localtimenow.tm_min, nowsecs]
  
#### External functions for printing data
  def display_heating_schedule(self):
    self.heat_schedule.display()
      
  def display_water_schedule(self):
    if not self.water_schedule is None:
      self.water_schedule.display()

  def printTarget(self):
      
    current_state = self.getTempState()
    
    if current_state == self.TEMP_STATE_OFF:
      return "controller off without frost protection"
    elif current_state == self.TEMP_STATE_OFF_FROST:
      return "controller off"
    elif current_state == self.TEMP_STATE_HOLIDAY:
      return "controller on holiday for %i hours" % self.holidayhours
    elif current_state == self.TEMP_STATE_FROST:
      return "controller in frost mode"
    elif current_state == self.TEMP_STATE_HELD:
      return "temp held for %i mins at %i"%(self.tempholdmins, self.setroomtemp)
    elif current_state == self.TEMP_STATE_OVERRIDDEN:
      locatimenow = self._localtimearray()
      nexttarget = self.heat_schedule.getNextScheduleItem(locatimenow)
      return "temp overridden to %0.1f until %02d:%02d" % (self.setroomtemp, nexttarget[1], nexttarget[2])
    elif current_state == self.TEMP_STATE_PROGRAM:
      locatimenow = self._localtimearray()
      nexttarget = self.heat_schedule.getNextScheduleItem(locatimenow)
      return "temp set to %0.1f until %02d:%02d" % (self.setroomtemp, nexttarget[1], nexttarget[2])
    
  def _check_data_age(self, maxage, *fieldnames):
    #field data age is not more than maxage (in seconds)
    if len(fieldnames) == 0:
      raise ValueError("Must list at least one field")
    
    for fieldname in fieldnames:
      if not self._check_data_present(fieldname):
        return False
      if time.time() - self.datareadtime[fieldname] > maxage:
        logging.warning("C%i data item %s too old"%(self.address, fieldname))
        return False
    return True
    
  def _check_data_present(self, *fieldnames):
    if len(fieldnames) == 0:
      raise ValueError("Must list at least one field")

    for fieldname in fieldnames:
      if self.datareadtime[fieldname] == None:
        logging.warning("C%i data item %s not avaliable"%(self.address, fieldname))
        return False
    return True
        
#### External functions for getting data

  def getAirSensorType(self):
    if not self._check_data_present('sensorsavaliable'):
      return False

    if self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_FLOOR:
      return 1
    elif self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_FLOOR:
      return 2
    else:
      return 0
      
  def getAirTemp(self):
    if not self._check_data_present('sensorsavaliable'):
      return False
    
    if self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_FLOOR:
      if not self._check_data_age(10, 'airtemp'):
        return False
      return self.airtemp
    elif self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_FLOOR:
      if not self._check_data_age(10, 'remoteairtemp'):
        return False
      return self.remoteairtemp
    else:
      return False
     
#### External functions for setting data

  def setHeatingSchedule(self, day, schedule):
    padschedule = self.heat_schedule.pad_schedule(schedule)
    self.network.hmSetFields(self.address,self.protocol,day,padschedule)
    
  def setWaterSchedule(self, day, schedule):
    padschedule = self.water_schedule.pad_schedule(schedule)
    if day == 'all':
      self.network.hmSetFields(self.address,self.protocol,'mon_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'tues_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'wed_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'thurs_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'fri_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'sat_water',padschedule)
      self.network.hmSetFields(self.address,self.protocol,'sun_water',padschedule)
    else:
      self.network.hmSetFields(self.address,self.protocol,day,padschedule)

  def setTime(self) :
      """set time on controller to match current localtime on server"""
      return self.hmSetFields(self.address,self.protocol,'currenttime',_localtimearray())
      
#general field setting

  def setField(self,field,value):
    return self.network.hmSetField(self.address,self.protocol,field,value)

  def setFields(self,field,value):
    return self.network.hmSetFields(self.address,self.protocol,field,value)

#overriding      
      
  def setTemp(self, temp) :
    #sets the temperature demand overriding the program. Believe it returns at next prog change.
  
    #check hold temp not applied
    if self.readField('tempholdmins') == 0:
      return self.network.hmSetField(self.address,self.protocol,'setroomtemp',temp)
    else:
      logging.warn("%i address, temp hold applied so won't set temp"%(self.address))

  def releaseTemp(self) :
    #release SetTemp back to the program, but only if temp isn't held
    if self.readField('tempholdmins') == 0:
      return self.network.hmSetField(self.address,self.protocol,'tempholdmins',0)
    else:
      logging.warn("%i address, temp hold applied so won't remove set temp"%(self.address))     

  def holdTemp(self, minutes, temp) :
    #sets the temperature demand overrding the program for a set time. Believe it then returns to program.
    self.network.hmSetField(self.address,self.protocol,'setroomtemp',temp)
    return self.network.hmSetField(self.address,self.protocol,'tempholdmins',minutes)
    #didn't stay on if did minutes followed by temp.
    
  def releaseHoldTemp(self) :
    #release SetTemp or HoldTemp back to the program
    return self.network.hmSetField(self.address,self.protocol,'tempholdmins',0)
    
  def setHoliday(self, hours) :
    #sets holiday up for a defined number of hours
    return self.network.hmSetField(self.address,self.protocol,'holidayhours',hours)
  
  def releaseHoliday(self) :
    #cancels holiday mode
    return self.network.hmSetField(self.address,self.protocol,'holidayhours',0)

#onoffs

  def setOn(self):
    return self.network.hmSetField(self.address,self.protocol,'onoff',WRITE_ONOFF_ON)
  def setOff(self):
    return self.network.hmSetField(self.address,self.protocol,'onoff',WRITE_ONOFF_OFF)
    
  def setHeat(self):
    return self.network.hmSetField(self.address,self.protocol,'runmode',WRITE_RUNMODE_HEATING)
  def setFrost(self):
    return self.network.hmSetField(self.address,self.protocol,'runmode',WRITE_RUNMODE_FROST)
    
  def setLock(self):
    return self.network.hmSetField(self.address,self.protocol,'keylock',WRITE_KEYLOCK_ON)
  def setUnlock(self):
    return self.network.hmSetField(self.address,self.protocol,'keylock',WRITE_KEYLOCK_OFF)
  
#other
#set floor limit
#set holiday


class hmBroadcastController(hmController):
  #create a controller that only broadcasts
  def __init__(self, network, short_name, long_name):
    super(hmBroadcastController, self).__init__(network, BROADCAST_ADDR, DEFAULT_PROTOCOL, short_name, long_name, False, DEFAULT_PROG_MODE)
  
  ##add methods to block or remove get functions
