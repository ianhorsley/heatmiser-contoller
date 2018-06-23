"""Heatmiser Device Classes

Modules handle all the DCB and fields for each device on the Heatmiser network

Ian Horsley 2018
"""

#read = return local if not to old, otherwise gets
#get = goes to network to get
#each field should it's own maximum age

import logging
import time
import serial

from hm_constants import *
from .exceptions import HeatmiserResponseError, HeatmiserControllerTimeError
from schedule_functions import SchedulerDayHeat, SchedulerWeekHeat, SchedulerDayWater, SchedulerWeekWater, SCH_ENT_TEMP
from decorators import ListWrapperClass, run_function_on_all

class HeatmiserDevice(object):
    """General device class for thermostats"""
    ## Variables used by code
    lastreadtime = 0 #records last time of a successful read

    ## Initialisation functions and low level functions
    def __init__(self, adaptor, devicesettings, generalsettings=None):
        #address, protocol, short_name, long_name, model, mode
        self._adaptor = adaptor

        self.water_schedule = None

        #initialise data structures
        self._uniquetodcb = []
        self._fieldsvalid = []
        self._buildfieldtables()
        self.data = dict.fromkeys(self._fieldnametonum.keys(), None)
        self.datareadtime = dict.fromkeys(self._fieldnametonum.keys(), None)

        self._update_settings(devicesettings, generalsettings)

        self.rawdata = [None] * self.dcb_length

    def _update_settings(self, settings, generalsettings):
        """Check settings and update if needed."""

        if not generalsettings is None:
            for name, value in generalsettings.iteritems():
                setattr(self, '_' + name, value)

        for name, value in settings.iteritems():
            setattr(self, '_' + name, value)

        self.address = self._address #make externally available
        del self._address

        if self._expected_prog_mode == PROG_MODE_DAY:
            self.heat_schedule = SchedulerDayHeat()
            if self.isHotWater():
                self.water_schedule = SchedulerDayWater()
        elif self._expected_prog_mode == PROG_MODE_WEEK:
            self.heat_schedule = SchedulerWeekHeat()
            if self.isHotWater():
                self.water_schedule = SchedulerWeekWater()
        else:
            raise ValueError("Unknown program mode")

        self._expected_prog_mode_number = PROG_MODES[self._expected_prog_mode]

        self._fieldranges = FIELDRANGES[self._expected_model][self._expected_prog_mode]

        if self._expected_model == 'prt_e_model':
            self.dcb_map = PRTEmap[self._expected_prog_mode]
        elif self._expected_model == 'prt_hw_model':
            self.dcb_map = PRTHWmap[self._expected_prog_mode]
        elif self._expected_model == False:
            self.dcb_map = STRAIGHTmap
        else:
            raise ValueError("Unknown model %s"%self._expected_model)

        self._build_dcb_tables()

        self._expected_model_number = DEVICE_MODELS[self._expected_model]

        if self.dcb_map[0][1] != DCB_INVALID:
            self.dcb_length = self.dcb_map[0][0] - self.dcb_map[0][1] + 1
        elif self.dcb_map[1][1] != DCB_INVALID:
            self.dcb_length = self.dcb_map[1][0] - self.dcb_map[1][1] + 1
        else:
            raise ValueError("DCB map length not found")

        self.fullreadtime = self._estimateReadTime(self.dcb_length)
        
    def _get_dcb_address(self, uniqueaddress):
        """get the DCB address for a controller from the unique address"""
        return self._uniquetodcb[uniqueaddress]
    
    def _buildfieldtables(self):
        """build dict to map field name to index"""
        self._fieldnametonum = {}
        for key, data in enumerate(fields):
            fieldname = data[FIELD_NAME]
            self._fieldnametonum[fieldname] = key
                
    def _build_dcb_tables(self):
        """build list to map unique to dcb address and list of valid fields """
        #build a forward lookup table for the DCB values from unique address
        self._uniquetodcb = range(MAX_UNIQUE_ADDRESS+1)
        for uniquemax, offsetsel in self.dcb_map:
            self._uniquetodcb[0:uniquemax + 1] = [x - offsetsel for x in range(uniquemax + 1)] if not offsetsel is DCB_INVALID else [DCB_INVALID] * (uniquemax + 1)
        
        #build list of valid fields for this device
        self._fieldsvalid = [False] * len(fields)
        for first, last in self._fieldranges:
            self._fieldsvalid[self._fieldnametonum[first]: self._fieldnametonum[last] + 1] = [True] * (self._fieldnametonum[last] - self._fieldnametonum[first] + 1)
        #self._fullDCB = sum(x is not None for x in self._uniquetodcb))
        logging.debug("C%i Fieldsvalid %s"%(self.address, ','.join(str(int(x)) for x in self._fieldsvalid)))
    
    def _check_data_age(self, fieldnames, maxagein=None):
        """Check field data age is not more than maxage (in seconds)
        fieldnames can be list or string
        
        maxage = None, use the default from fields
        maxage = -1, only check if present
        maxage >=0, use maxage (0 is effectively always False)
        return False if old, True if recent"""
        if len(fieldnames) == 0:
            raise ValueError("Must list at least one field")
        
        if not isinstance(fieldnames, list):
            fieldnames = [fieldnames]
        
        for fieldname in fieldnames:
            if not self._check_data_present(fieldname):
                return False
            elif maxagein == -1: #only check present
                return True
            elif maxagein == None: #if none use field defaults
                maxage = fields[self._fieldnametonum[fieldname]][FIELD_MAX_AGE]
            else:
                maxage = maxagein
            #now check time
            if time.time() - self.datareadtime[fieldname] > maxage:
                logging.debug("C%i data item %s too old"%(self.address, fieldname))
                return False
        return True
        
    def _check_data_present(self, *fieldnames):
        """Check field(s) has data"""
        if len(fieldnames) == 0:
            raise ValueError("Must list at least one field")

        for fieldname in fieldnames:
            if self.datareadtime[fieldname] == None:
                logging.debug("C%i data item %s not available"%(self.address, fieldname))
                return False
        return True
    
    ## Basic reading and getting functions
    
    def read_all(self):
        try:
            self.rawdata = self._adaptor.read_all_from_device(self.address, self._protocol, self.dcb_length)
        except serial.SerialException as err:

            logging.warn("C%i Read all failed, Serial Port error %s"%(self.address, str(err)))
            raise
        else:
            logging.info("C%i Read all"%(self.address))

            self.lastreadtime = time.time()
            self._procpayload(self.rawdata)
            return self.rawdata

    def read_field(self, fieldname, maxage=None):
        """Returns a fields value, gets from the device if to old"""
        #return field value
        #get field from network if
        # maxage = None, older than the default from fields
        # maxage = -1, not read before
        # maxage >=0, older than maxage
        # maxage = 0, always
        if maxage == 0 or not self._check_data_age(fieldname, maxage):
            if self._autoreadall is True:
                self.get_field_range(fieldname)
            else:
                raise ValueError("Need to read %s first"%fieldname)
        return self.data[fieldname]
    
    def read_fields(self, fieldnames, maxage=None):
        """Returns a list of field values, gets from the device if any are to old"""
        #find which fields need getting because to old
        fieldids = [self._fieldnametonum[fieldname] for fieldname in fieldnames if self._fieldsvalid[self._fieldnametonum[fieldname]] and (maxage == 0 or not self._check_data_age(fieldname, maxage))]
        
        fieldids = list(set(fieldids)) #remove duplicates, ordering doesn't matter
        
        if len(fieldids) > 0 and self._autoreadall is True:
            self._get_fields(fieldids)
        elif len(fieldids) > 0:
            raise ValueError("Need to read fields first")
        return [self.data[fieldname] for fieldname in fieldnames]
    
    def get_variables(self):
        self.get_field_range('setroomtemp', 'hotwaterdemand')
        
    def get_temps_and_demand(self):
        self.get_field_range('remoteairtemp', 'hotwaterdemand')
    
    def get_field_range(self, firstfieldname, lastfieldname = None):
        """gets fieldrange from device
        
        safe for blocks crossing gaps in dcb"""
        if lastfieldname == None:
            lastfieldname = firstfieldname

        blockstoread = self._get_field_blocks_from_range(firstfieldname, lastfieldname)
        logging.debug(blockstoread)
        estimatedreadtime = self._estimateBlocksReadTime(blockstoread)
        
        if estimatedreadtime < self.fullreadtime - 0.02: #if to close to full read time, then read all
            try:
                for firstfieldid, lastfieldid, blocklength in blockstoread:
                    logging.debug("C%i Reading ui %i to %i len %i, proc %s to %s"%(self.address, fields[firstfieldid][FIELD_ADD],fields[lastfieldid][FIELD_ADD],blocklength,fields[firstfieldid][FIELD_NAME], fields[lastfieldid][FIELD_NAME]))
                    rawdata = self._adaptor.read_from_device(self.address, self._protocol, fields[firstfieldid][FIELD_ADD], blocklength)
                    self.lastreadtime = time.time()
                    self._procpartpayload(rawdata, fields[firstfieldid][FIELD_NAME], fields[lastfieldid][FIELD_NAME])
            except serial.SerialException as err:
                logging.warn("C%i Read failed of fields %s to %s, Serial Port error %s"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH), str(err)))
                raise
            else:
                logging.info("C%i Read fields %s to %s, in %i blocks"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH),len(blockstoread)))
        else:
            logging.debug("C%i Read fields %s to %s by read_all, %0.3f %0.3f"%(self.address, firstfieldname.ljust(FIELD_NAME_LENGTH),lastfieldname.ljust(FIELD_NAME_LENGTH), estimatedreadtime, self.fullreadtime))
            self.read_all()

    def _get_fields(self, fieldids):
        #reads fields from controller, safe for blocks crossing gaps in dcb
        
        blockstoread = self._getFieldBlocksFromListById(fieldids)
        logging.debug(blockstoread)
        estimatedreadtime = self._estimateBlocksReadTime(blockstoread)
        
        if estimatedreadtime < self.fullreadtime - 0.02: #if to close to full read time, then read all
            try:
                for firstfieldid, lastfieldid, blocklength in blockstoread:
                    logging.debug("C%i Reading ui %i to %i len %i, proc %s to %s"%(self.address, fields[firstfieldid][FIELD_ADD], fields[lastfieldid][FIELD_ADD], blocklength, fields[firstfieldid][FIELD_NAME], fields[lastfieldid][FIELD_NAME]))
                    rawdata = self._adaptor.read_from_device(self.address, self._protocol, fields[firstfieldid][FIELD_ADD], blocklength)
                    self.lastreadtime = time.time()
                    self._procpartpayload(rawdata, fields[firstfieldid][FIELD_NAME], fields[lastfieldid][FIELD_NAME])
            except serial.SerialException as err:
                logging.warn("C%i Read failed of fields %s, Serial Port error %s"%(self.address, ', '.join(fields[id][FIELD_NAME] for id in fieldids), str(err)))
                raise
            else:
                logging.info("C%i Read fields %s in %i blocks"%(self.address, ', '.join(fields[id][FIELD_NAME] for id in fieldids),len(blockstoread)))
                    
        else:
            logging.debug("C%i Read fields %s by read_all, %0.3f %0.3f"%(self.address, ', '.join(fields[id][FIELD_NAME] for id in fieldids), estimatedreadtime, self.fullreadtime))
            self.read_all()
                
        #data can only be requested from the controller in contiguous blocks
        #functions takes a first and last field and separates out the individual blocks available for the controller type
        #return, fieldstart, fieldend, length of read in bytes
    def _get_field_blocks_from_range(self, firstfieldname, lastfieldname):
        firstfieldid = self._fieldnametonum[firstfieldname]
        lastfieldid = self._fieldnametonum[lastfieldname]
        return self._getFieldBlocksFromRangeById(firstfieldid,lastfieldid)
        
    def _getFieldBlocksFromRangeById(self,firstfieldid,lastfieldid):
        blocks = []
        previousfieldvalid = False

        for fieldnum, fieldvalid in enumerate(self._fieldsvalid[firstfieldid:lastfieldid + 1],firstfieldid):
            if previousfieldvalid is False and not fieldvalid is False:
                start = fieldnum
            elif not previousfieldvalid is False and fieldvalid is False:
                blocks.append([start,fieldnum - 1,fields[fieldnum - 1][FIELD_ADD] + fields[fieldnum - 1][FIELD_LEN] - fields[start][FIELD_ADD]])
            
            previousfieldvalid = fieldvalid

        if not previousfieldvalid is False:
            blocks.append([start,lastfieldid,fields[lastfieldid][FIELD_ADD] + fields[lastfieldid][FIELD_LEN] - fields[start][FIELD_ADD]])
        return blocks
    
    def _getFieldBlocksFromListById(self,fieldids):
        #find blocks between lowest and highest field
        fieldblocks = self._getFieldBlocksFromRangeById(min(fieldids),max(fieldids))
        
        readblocks = []
        for block in fieldblocks:
            #find fields in that block
            inblock = [id for id in fieldids if block[0] <= id <= block[1]]
            if len(inblock) > 0:
                #if single read is shorter than individual
                readlen = fields[max(inblock)][FIELD_LEN] + fields[max(inblock)][FIELD_ADD] - fields[min(inblock)][FIELD_ADD]
                if self._estimateReadTime(readlen) < sum([ self._estimateReadTime(fields[id][FIELD_LEN]) for id in inblock]):
                    readblocks.append([min(inblock),max(inblock),readlen])
                else:
                    for ids in inblock:
                        readblocks.append([ids,ids,fields[ids][FIELD_LEN]])
        return readblocks
    
    def _estimateBlocksReadTime(self,blocks):
        #estimates read time for a set of blocks, including the COM_BUS_RESET_TIME between blocks
        #excludes the COM_BUS_RESET_TIME before first block
        readtimes = [self._estimateReadTime(x[2]) for x in blocks]
        return sum(readtimes) + self._adaptor.min_time_between_reads() * (len(blocks) - 1)
    
    @staticmethod
    def _estimateReadTime(length):
        #estiamtes the read time for a call to read_from_device without COM_BUS_RESET_TIME
        #based on empirical measurements of one prt_hw_model and 5 prt_e_model
        return length * 0.002075 + 0.070727
    
    def _procfield(self,data,fieldinfo):
        fieldname = fieldinfo[FIELD_NAME]
        length = fieldinfo[FIELD_LEN]
        factor = fieldinfo[FIELD_DIV]
        fieldrange = fieldinfo[FIELD_RANGE]
        #logging.debug("Processing %s %s"%(fieldinfo[FIELD_NAME],', '.join(str(x) for x in data)))
        if length == 1:
            value = data[0]/factor
        elif length == 2:
            val_high = data[0]
            val_low    = data[1]
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
    
        if len(fieldrange) == 2 and isinstance(fieldrange[0], (int, long)) and isinstance(fieldrange[1], (int, long)):
            if value < fieldrange[0] or value > fieldrange[1]:
                raise HeatmiserResponseError("Field value %i outside expected range"%value)
        
        if fieldname == 'DCBlen' and value != self.dcb_length:
            raise HeatmiserResponseError('DCBlengh is unexpected')
        
        if fieldname == 'model' and value != self._expected_model_number:
            raise HeatmiserResponseError('Model is unexpected')
        
        if fieldname == 'programmode' and value != self._expected_prog_mode_number:
            raise HeatmiserResponseError('Programme mode is unexpected')
        
        if fieldname == 'version' and self._expected_model != 'prt_hw_model':
            value = data[0] & 0x7f
            self.floorlimiting = data[0] >> 7
            self.data['floorlimiting'] = self.floorlimiting
        
        self.data[fieldname] = value
        setattr(self, fieldname, value)
        self.datareadtime[fieldname] = self.lastreadtime
        
        if fieldname == 'currenttime':
            self._checkcontrollertime()
        
        ###todo, add range validation for other lengths

    def _procpartpayload(self, rawdata, firstfieldname, lastfieldname):
        #rawdata must be a list
        #converts field names to unique addresses to allow process of shortened raw data
        logging.debug("C%i Processing Payload from field %s to %s"%(self.address,firstfieldname,lastfieldname) )
        firstfieldid = self._fieldnametonum[firstfieldname]
        lastfieldid = self._fieldnametonum[lastfieldname]
        self._procpayload(rawdata, firstfieldid, lastfieldid)
        
    def _procpayload(self, rawdata, firstfieldid = 0, lastfieldid = len(fields)):
        logging.debug("C%i Processing Payload from field %i to %i"%(self.address,firstfieldid,lastfieldid) )

        fullfirstdcbadd = self._get_dcb_address(fields[firstfieldid][FIELD_ADD])
        
        for fieldinfo in fields[firstfieldid:lastfieldid + 1]:
            uniqueaddress = fieldinfo[FIELD_ADD]
            
            length = fieldinfo[FIELD_LEN]
            dcbadd = self._get_dcb_address(uniqueaddress)

            if dcbadd == DCB_INVALID:
                setattr(self, fieldinfo[FIELD_NAME], None)
                self.data[fieldinfo[FIELD_NAME]] = None
            else:
                dcbadd -= fullfirstdcbadd #adjust for the start of the request
                
                try:
                    self._procfield(rawdata[dcbadd:dcbadd+length], fieldinfo)
                except HeatmiserResponseError as err:
                    logging.warn("C%i Field %s process failed due to %s"%(self.address, fieldinfo[FIELD_NAME], str(err)))

        self.rawdata[fullfirstdcbadd:fullfirstdcbadd+len(rawdata)] = rawdata

    def _checkcontrollertime(self):
        #run compare of times, and try to fix if _autocorrectime
        try:
            self._comparecontrollertime()
        except HeatmiserControllerTimeError:
            if self._autocorrectime is True:
                self.setTime()
            else:
                raise
    
    def _comparecontrollertime(self):
        # Now do same sanity checking
        # Check the time is within range
        # currentday is numbered 1-7 for M-S
        # localday (python) is numbered 0-6 for Sun-Sat
        
        if not self._check_data_present('currenttime'):
            raise HeatmiserResponseError("Time not read before check")

        localtimearray = self._localtimearray(self.datareadtime['currenttime']) #time that time field was read
        localweeksecs = self._weeksecs(localtimearray)
        remoteweeksecs = self._weeksecs(self.data['currenttime'])
        directdifference = abs(localweeksecs - remoteweeksecs)
        wrappeddifference = abs(self.DAYSECS * 7 - directdifference) #compute the difference on rollover
        self.timeerr = min(directdifference, wrappeddifference)
        logging.debug("Local time %i, remote time %i, error %i"%(localweeksecs,remoteweeksecs,self.timeerr))

        if self.timeerr > self.DAYSECS:
                raise HeatmiserControllerTimeError("C%2d Incorrect day : local is %s, sensor is %s" % (self.address, localtimearray[CURRENT_TIME_DAY], self.data['currenttime'][CURRENT_TIME_DAY]))

        if (self.timeerr > TIME_ERR_LIMIT):
                raise HeatmiserControllerTimeError("C%2d Time Error %d greater than %d: local is %s, sensor is %s" % (self.address, self.timeerr, TIME_ERR_LIMIT, localweeksecs, remoteweeksecs))

    @staticmethod
    def _localtimearray(timenow = time.time()):
        #creates an array in heatmiser format for local time. Day 1-7, 1=Monday
        #input time.time() (not local)
        localtimenow = time.localtime(timenow)
        nowday = localtimenow.tm_wday + 1    #python tm_wday, range [0, 6], Monday is 0
        nowsecs = min(localtimenow.tm_sec, 59) #python tm_sec range[0, 61]
        
        return [nowday, localtimenow.tm_hour, localtimenow.tm_min, nowsecs]
    
    DAYSECS = 86400
    HOURSECS = 3600
    MINSECS = 60
    def _weeksecs(self, localtimearray):
        #calculates the time from the start of the week in seconds from a heatmiser time array
        return ( localtimearray[CURRENT_TIME_DAY] - 1 ) * self.DAYSECS + localtimearray[CURRENT_TIME_HOUR] * self.HOURSECS + localtimearray[CURRENT_TIME_MIN] * self.MINSECS + localtimearray[CURRENT_TIME_SEC]
    
    ## Basic set field functions
    
    def setField(self, fieldname, payload):
        #set a field (single member of fields) to a state or payload. Defined for all field lengths.
        fieldinfo = fields[self._fieldnametonum[fieldname]]
        
        if len(fieldinfo) < FIELD_WRITE + 1 or fieldinfo[FIELD_WRITE] != 'W':
                #check that write is part of field info and is 'W'
                raise ValueError("setField: field isn't writeable")
                             
        self._checkPayloadValues(payload, fieldinfo)

        if fieldinfo[FIELD_LEN] == 1:
                payload = [payload]
        elif fieldinfo[FIELD_LEN] == 2:
                pay_lo = (payload & BYTEMASK)
                pay_hi = (payload >> 8) & BYTEMASK
                payload = [pay_lo, pay_hi]
        try:
                self._adaptor.write_to_device(self.address, self._protocol, fieldinfo[FIELD_ADD], fieldinfo[FIELD_LEN], payload)
        except:
                logging.info("C%i failed to set field %s to %s"%(self.address, fieldname.ljust(FIELD_NAME_LENGTH), ', '.join(str(x) for x in payload)))
                raise
        else:
                logging.info("C%i set field %s to %s"%(self.address, fieldname.ljust(FIELD_NAME_LENGTH), ', '.join(str(x) for x in payload)))
        
        self.lastreadtime = time.time()
        
        ###should really be handled by a specific overriding function, rather than in here.
        #handle odd effect on WRITE_hotwaterdemand_PROG
        if fieldname == 'hotwaterdemand':
            if payload[0] == WRITE_HOTWATERDEMAND_PROG: #returned to program so outcome is unknown
                self.datareadtime[fieldname] = None
                return
            elif payload[0] == WRITE_HOTWATERDEMAND_OFF: #if overridden off store the off read value
                payload[0] = READ_HOTWATERDEMAND_OFF
        
        self._procpartpayload(payload,fieldname,fieldname)
        
    @staticmethod
    def _checkPayloadValues(payload, fieldinfo):
            #check the payload matches field details
            
            if fieldinfo[FIELD_LEN] in [1, 2] and not isinstance(payload, (int, long)):
                    #one or two byte field, not single length payload
                    raise TypeError("setField: invalid requested value")
            elif fieldinfo[FIELD_LEN] > 2 and len(payload) != fieldinfo[FIELD_LEN]:
                    #greater than two byte field, payload length must match field length
                    raise ValueError("setField: invalid payload length")
    
            #checks the payload matches the ranges if ranges are defined
            ranges = fieldinfo[FIELD_RANGE]
            if ranges != []:
                    if isinstance(payload, (int, long)):
                            if ( payload < ranges[0] or payload > ranges[1] ):
                                    raise ValueError("setField: payload out of range")
                    else:
                            for i, item in enumerate(payload):
                                    r = ranges[i % len(ranges)]
                                    if item < r[0] or item > r[1]:
                                            raise ValueError("setField: payload out of range")
    
    ## External functions for printing data
    def display_heating_schedule(self):
        self.heat_schedule.display()
            
    def display_water_schedule(self):
        if not self.water_schedule is None:
            self.water_schedule.display()

    def printTarget(self):
            
        current_state = self.readTempState()
        
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
            nexttarget = self.heat_schedule.get_next_schedule_item(locatimenow)
            return "temp overridden to %0.1f until %02d:%02d" % (self.setroomtemp, nexttarget[1], nexttarget[2])
        elif current_state == self.TEMP_STATE_PROGRAM:
            locatimenow = self._localtimearray()
            nexttarget = self.heat_schedule.get_next_schedule_item(locatimenow)
            return "temp set to %0.1f until %02d:%02d" % (self.setroomtemp, nexttarget[1], nexttarget[2])
    
    ## External functions for reading data

    def isHotWater(self):
        #returns True if stat is a model with hotwater control, False otherwise
        return self._expected_model == 'prt_hw_model'

    TEMP_STATE_OFF = 0    #thermostat display is off and frost protection disabled
    TEMP_STATE_OFF_FROST = 1 #thermostat display is off and frost protection enabled
    TEMP_STATE_FROST = 2 #frost protection enabled indefinitely
    TEMP_STATE_HOLIDAY = 3 #holiday mode, frost protection for a period
    TEMP_STATE_HELD = 4 #temperature held for a number of hours
    TEMP_STATE_OVERRIDDEN = 5 #temperature overridden until next program time
    TEMP_STATE_PROGRAM = 6 #following program
    
    def readTempState(self):
        self.read_fields(['mon_heat','tues_heat','wed_heat','thurs_heat','fri_heat','wday_heat','wend_heat'],-1)
        self.read_fields(['onoff','frostprot','holidayhours','runmode','tempholdmins','setroomtemp'])
        
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
        
            if not self._check_data_age(['currenttime'],MAX_AGE_MEDIUM):
                self.readTime()
            
            locatimenow = self._localtimearray()
            scheduletarget = self.heat_schedule.get_current_schedule_item(locatimenow)

            if scheduletarget[SCH_ENT_TEMP] != self.setroomtemp:
                return self.TEMP_STATE_OVERRIDDEN
            else:
                return self.TEMP_STATE_PROGRAM

    ### UNTESTED # last part about scheduletarget doesn't work
    def readWaterState(self):
        #does runmode affect hot water state?
        self.read_fields(['mon_water','tues_water','wed_water','thurs_water','fri_water','wday_water','wend_water'],-1)
        self.read_fields(['onoff','holidayhours','hotwaterdemand'])
        
        if self.onoff == WRITE_ONOFF_OFF:
            return self.TEMP_STATE_OFF
        elif self.holidayhours != 0:
            return self.TEMP_STATE_HOLIDAY
        else:
        
            if not self._check_data_age(['currenttime'], MAX_AGE_MEDIUM):
                self.readTime()
            
            locatimenow = self._localtimearray()
            scheduletarget = self.water_schedule.get_current_schedule_item(locatimenow)

            if scheduletarget[SCH_ENT_TEMP] != self.hotwaterdemand:
                return self.TEMP_STATE_OVERRIDDEN
            else:
                return self.TEMP_STATE_PROGRAM
                
    def readAirSensorType(self):
        if not self._check_data_present('sensorsavaliable'):
            return False

        if self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_FLOOR:
            return 1
        elif self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_FLOOR:
            return 2
        else:
            return 0
            
    def readAirTemp(self):
        #if not read before read sensorsavaliable field
        self.read_field('sensorsavaliable',None)
        
        if self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_FLOOR:
            return self.read_field('airtemp', self._max_age_temp)
        elif self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_FLOOR:
            return self.read_field('remoteairtemp', self._max_age_temp)
        else:
            raise ValueError("sensorsavaliable field invalid")
    
    def readRawData(self, startfieldname = None, endfieldname = None):
        if startfieldname == None or endfieldname == None:
            return self.rawdata
        else:
            return self.rawdata[self._get_dcb_address(uniadd[startfieldname][UNIADD_ADD]):self._get_dcb_address(uniadd[endfieldname][UNIADD_ADD])]
        
    def readTime(self, maxage = 0):
        return self.read_field('currenttime', maxage)
        
    ## External functions for setting data

    def setHeatingSchedule(self, day, schedule):
        padschedule = self.heat_schedule.pad_schedule(schedule)
        self.setField(day,padschedule)
        
    def setWaterSchedule(self, day, schedule):
        padschedule = self.water_schedule.pad_schedule(schedule)
        if day == 'all':
            self.setField('mon_water',padschedule)
            self.setField('tues_water',padschedule)
            self.setField('wed_water',padschedule)
            self.setField('thurs_water',padschedule)
            self.setField('fri_water',padschedule)
            self.setField('sat_water',padschedule)
            self.setField('sun_water',padschedule)
        else:
            self.setField(day,padschedule)

    def setTime(self) :
            """set time on controller to match current localtime on server"""
            timenow = time.time() + 0.5 #allow a little time for any delay in setting
            return self.setField('currenttime',self._localtimearray(timenow))

    #overriding

    def setTemp(self, temp) :
        #sets the temperature demand overriding the program. Believe it returns at next prog change.
        if self.read_field('tempholdmins') == 0: #check hold temp not applied
            return self.setField('setroomtemp',temp)
        else:
            logging.warn("%i address, temp hold applied so won't set temp"%(self.address))

    def releaseTemp(self) :
        #release SetTemp back to the program, but only if temp isn't held
        if self.read_field('tempholdmins') == 0: #check hold temp not applied
            return self.setField('tempholdmins',0)
        else:
            logging.warn("%i address, temp hold applied so won't remove set temp"%(self.address))

    def holdTemp(self, minutes, temp) :
        #sets the temperature demand overrding the program for a set time. Believe it then returns to program.
        self.setField('setroomtemp',temp)
        return self.setField('tempholdmins',minutes)
        #didn't stay on if did minutes followed by temp.
        
    def releaseHoldTemp(self) :
        #release SetTemp or HoldTemp back to the program
        return self.setField('tempholdmins',0)
        
    def setHoliday(self, hours) :
        #sets holiday up for a defined number of hours
        return self.setField('holidayhours',hours)
    
    def releaseHoliday(self) :
        #cancels holiday mode
        return self.setField('holidayhours',0)

    #onoffs

    def setOn(self):
        return self.setField('onoff',WRITE_ONOFF_ON)
    def setOff(self):
        return self.setField('onoff',WRITE_ONOFF_OFF)
        
    def setHeat(self):
        return self.setField('runmode',WRITE_RUNMODE_HEATING)
    def setFrost(self):
        return self.setField('runmode',WRITE_RUNMODE_FROST)
        
    def setLock(self):
        return self.setField('keylock',WRITE_KEYLOCK_ON)
    def setUnlock(self):
        return self.setField('keylock',WRITE_KEYLOCK_OFF)
    
#other
#set floor limit
#set holiday

#create a controller that broadcasts or reads from multiple stats
class HeatmiserBroadcastDevice(HeatmiserDevice):
    """Broadcast device class for broadcast set functions and managing reading on all devices"""
    _controllerlist = ListWrapperClass()

    def __init__(self, network, long_name, controllerlist=None):
        self._controllerlist.list = controllerlist
        settings = {
            'address':BROADCAST_ADDR,
            'display_order': 0,
            'long_name': long_name,
            'protocol':DEFAULT_PROTOCOL,
            'expected_model':False,
            'expected_prog_mode':DEFAULT_PROG_MODE
            }
        super(HeatmiserBroadcastDevice, self).__init__(network, settings)
    
    #run read functions on all stats
    @run_function_on_all(_controllerlist)
    def read_field(self, fieldname, maxage = None):
        logging.info("All reading %s from %i controllers"%(fieldname, len(self._controllerlist.list)))
            
    @run_function_on_all(_controllerlist)
    def read_fields(self, fieldnames, maxage = None):
        logging.info("All reading %s from %i controllers"%(', '.join([fieldname for fieldname in fieldnames]), len(self._controllerlist.list)))
        
    @run_function_on_all(_controllerlist)
    def readAirTemp(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def readTempState(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def readWaterState(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def readAirSensorType(self):
        pass
            
    @run_function_on_all(_controllerlist)
    def readTime(self, maxage = 0):
        pass
    
    #run set functions which require a read on all stats
    @run_function_on_all(_controllerlist)
    def setTemp(self, temp):
        pass
    
    @run_function_on_all(_controllerlist)
    def releaseTemp(self):
        pass

