"""Heatmiser Device Classes

Thermostat classes on the Heatmiser network

Ian Horsley 2018
"""

#read = return local if not to old, otherwise gets
#get = goes to network to get
#each field should it's own maximum age

import logging
import time

from genericdevice import HeatmiserDevice
from fields import HeatmiserFieldSingle, HeatmiserFieldSingleReadOnly, HeatmiserFieldDouble, HeatmiserFieldDoubleReadOnly, HeatmiserFieldTime, HeatmiserFieldHeat, HeatmiserFieldWater, HeatmiserFieldHotWaterDemand, HeatmiserFieldDoubleReadOnlyTenths
from hm_constants import DEFAULT_PROTOCOL, DEFAULT_PROG_MODE, BROADCAST_ADDR, SLAVE_ADDR_MIN, SLAVE_ADDR_MAX, MAX_UNIQUE_ADDRESS
from hm_constants import MAX_AGE_LONG, MAX_AGE_MEDIUM, MAX_AGE_SHORT, MAX_AGE_USHORT
from hm_constants import DEVICE_MODELS, PROG_MODES
from .exceptions import HeatmiserResponseError, HeatmiserControllerTimeError
from schedule_functions import SchedulerDayHeat, SchedulerWeekHeat, SchedulerDayWater, SchedulerWeekWater, SCH_ENT_TEMP
from decorators import ListWrapperClass, run_function_on_all
from .logging_setup import csvlist

class ThermoStatWeek(HeatmiserDevice):
    """Device class for thermostats operating weekly programmode
    Heatmiser prt_e_model."""
    
    def __init__(self, adaptor, devicesettings, generalsettings={}):
        super(ThermoStatWeek, self).__init__(adaptor, devicesettings, generalsettings)
        self._expected_model_number = 3
        self._set_expected_field_values()
        #thermostat specific
        self.is_hot_water = False #returns True if stat is a model with hotwater control, False otherwise
    
    def _buildfields(self):
        """add to list of fields"""
        super(ThermoStatWeek, self)._buildfields()
        # list of fields can be sorted by key
        # dcb addresses could be computed from the completed field list and added to field.
        # all should have the first 4 fields, so put these in generic
        self.fields.extend([
            HeatmiserFieldSingleReadOnly('tempformat', 5, [0, 1], MAX_AGE_LONG),  # 00 C,  01 F
            HeatmiserFieldSingleReadOnly('switchdiff', 6, [1, 3], MAX_AGE_LONG),
            HeatmiserFieldSingleReadOnly('frostprot', 7, [0, 1], MAX_AGE_LONG),  #0=enable frost prot when display off,  (opposite in protocol manual,  but tested and user guide is correct)  (default should be enabled)
            HeatmiserFieldDoubleReadOnly('caloffset', 8, [], MAX_AGE_LONG),
            HeatmiserFieldSingleReadOnly('outputdelay', 10, [0, 15], MAX_AGE_LONG),  # minutes (to prevent rapid switching)
            HeatmiserFieldSingleReadOnly('address', 11, [SLAVE_ADDR_MIN, SLAVE_ADDR_MAX], MAX_AGE_LONG),
            HeatmiserFieldSingleReadOnly('updwnkeylimit', 12, [0, 10], MAX_AGE_LONG),   #limits use of up and down keys
            HeatmiserFieldSingleReadOnly('sensorsavaliable', 13, [0, 4], MAX_AGE_LONG),  #00 built in only,  01 remote air only,  02 floor only,  03 built in + floor,  04 remote + floor
            HeatmiserFieldSingleReadOnly('optimstart', 14, [0, 3], MAX_AGE_LONG),  # 0 to 3 hours,  default 0
            HeatmiserFieldSingleReadOnly('rateofchange', 15, [], MAX_AGE_LONG),  #number of minutes per degree to raise the temperature,  default 20. Applies to the Wake and Return comfort levels (1st and 3rd)
            HeatmiserFieldSingleReadOnly('programmode', 16, [0, 1], MAX_AGE_LONG),  #0=5/2,  1= 7day
            HeatmiserFieldSingle('frosttemp', 17, [7, 17], MAX_AGE_LONG),  #default is 12,  frost protection temperature
            HeatmiserFieldSingle('setroomtemp', 18, [5, 35], MAX_AGE_USHORT),
            HeatmiserFieldSingle('floormaxlimit', 19, [20, 45], MAX_AGE_LONG),
            HeatmiserFieldSingleReadOnly('floormaxlimitenable', 20, [0, 1], MAX_AGE_LONG),  #1=enable
            HeatmiserFieldSingle('onoff', 21, [0, 1], MAX_AGE_SHORT),  #1 = on
            HeatmiserFieldSingle('keylock', 22, [0, 1], MAX_AGE_SHORT),  #1 = on
            HeatmiserFieldSingle('runmode', 23, [0, 1], MAX_AGE_SHORT),   #0 = heating mode,  1 = frost protection mode
            HeatmiserFieldDouble('holidayhours', 24, [0, 720], MAX_AGE_SHORT),  #range guessed and tested,  setting to 0 cancels hold and puts back to program 
            #HeatmiserFieldUnknown('unknown', 26, 1, [], MAX_AGE_LONG, 6),  # gap from 26 to 31
            HeatmiserFieldDouble('tempholdmins', 32, [0, 5760], MAX_AGE_SHORT),  #range guessed and tested,  setting to 0 cancels hold and puts setroomtemp back to program
            HeatmiserFieldDoubleReadOnlyTenths('remoteairtemp', 34, [], MAX_AGE_USHORT),  #ffff if no sensor
            HeatmiserFieldDoubleReadOnlyTenths('floortemp', 36, [], MAX_AGE_USHORT),  #ffff if no sensor
            HeatmiserFieldDoubleReadOnlyTenths('airtemp', 38, [], MAX_AGE_USHORT),  #ffff if no sensor
            HeatmiserFieldSingleReadOnly('errorcode', 40, [0, 3], MAX_AGE_SHORT),  # 0 is no error # errors,  0 built in,  1,  floor,  2 remote
            HeatmiserFieldSingleReadOnly('heatingdemand', 41, [0, 1], MAX_AGE_USHORT),  #0 none,  1 heating currently
            HeatmiserFieldTime('currenttime', 43, [[1, 7], [0, 23], [0, 59], [0, 59]], MAX_AGE_USHORT),  #day (Mon - Sun),  hour,  min,  sec.
            #5/2 progamming #if hour = 24 entry not used
            HeatmiserFieldHeat('wday_heat', 47, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),  #hour,  min,  temp  (should minutes be only 0 and 30?)
            HeatmiserFieldHeat('wend_heat', 59, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM)
            ])
            
        self.water_schedule = None
        self.heat_schedule = SchedulerWeekHeat()
    
    def _checkcontrollertime(self):
        """run check of device time against local read time, and try to fix if _autocorrectime"""
        try:
            self.currenttime.comparecontrollertime()
        except HeatmiserControllerTimeError:
            if self.autocorrectime is True:
                ### Add warning that attempting to fix.
                self.set_time()
            else:
                raise
    
    def get_variables(self):
        """Gets setroomtemp to hotwaterdemand fields from device"""
        self.get_field_range('setroomtemp', 'hotwaterdemand')
        
    def get_temps_and_demand(self):
        """Gets remoteairtemp to hotwaterdemand fields from device"""
        self.get_field_range('remoteairtemp', 'hotwaterdemand')
    
    ## External functions for printing data
    def display_heating_schedule(self):
        """Prints heating schedule to stdout"""
        self.heat_schedule.display()

    
    TEMP_STATE_OFF = 0    #thermostat display is off and frost protection disabled
    TEMP_STATE_OFF_FROST = 1 #thermostat display is off and frost protection enabled
    TEMP_STATE_FROST = 2 #frost protection enabled indefinitely
    TEMP_STATE_HOLIDAY = 3 #holiday mode, frost protection for a period
    TEMP_STATE_HELD = 4 #temperature held for a number of hours
    TEMP_STATE_OVERRIDDEN = 5 #temperature overridden until next program time
    TEMP_STATE_PROGRAM = 6 #following program
        
    target_texts = {
        TEMP_STATE_OFF: lambda self: "controller off without frost protection",
        TEMP_STATE_OFF_FROST: lambda self: "controller off",
        TEMP_STATE_HOLIDAY: lambda self: "controller on holiday for %s hours" % (self.holidayhours),
        TEMP_STATE_FROST: lambda self: "controller in frost mode",
        TEMP_STATE_HELD: lambda self: "temp held for %i mins at %i"%(self.tempholdmins, self.setroomtemp),
        TEMP_STATE_OVERRIDDEN: lambda self: "temp overridden to %0.1f until %02d:%02d" % (self.setroomtemp, self.nexttarget[1], self.nexttarget[2]),
        TEMP_STATE_PROGRAM: lambda self: "temp set to %0.1f until %02d:%02d" % (self.setroomtemp, self.nexttarget[1], self.nexttarget[2])
    }

    def nexttarget(self):
        """get next heat target"""
        return self.heat_schedule.get_next_schedule_item(self.currenttime.localtimearray())

    def print_target(self):
        """Returns text describing current heating state"""    
        current_state = self.read_temp_state()
        return self.target_texts[currernt_state](self)
            
    ## External functions for reading data
    
    def read_temp_state(self):
        """Returns the current temperature control state from off to following program"""
        self.read_fields(['mon_heat', 'tues_heat', 'wed_heat', 'thurs_heat', 'fri_heat', 'wday_heat', 'wend_heat'], -1)
        self.read_fields(['onoff', 'frostprot', 'holidayhours', 'runmode', 'tempholdmins', 'setroomtemp'])
        
        if self.onoff.value == WRITE_ONOFF_OFF and self.frostprot.value == READ_FROST_PROT_OFF:
            return self.TEMP_STATE_OFF
        elif self.onoff.value == WRITE_ONOFF_OFF and self.frostprot.value == READ_FROST_PROT_ON:
            return self.TEMP_STATE_OFF_FROST
        elif self.holidayhours.value != 0:
            return self.TEMP_STATE_HOLIDAY
        elif self.runmode.value == WRITE_RUNMODE_FROST:
            return self.TEMP_STATE_FROST
        elif self.tempholdmins.value != 0:
            return self.TEMP_STATE_HELD
        else:
            self.read_field('currenttime',MAX_AGE_MEDIUM)
            
            locatimenow = self.currenttime.localtimearray()
            scheduletarget = self.heat_schedule.get_current_schedule_item(locatimenow)

            if scheduletarget[SCH_ENT_TEMP] != self.setroomtemp:
                return self.TEMP_STATE_OVERRIDDEN
            else:
                return self.TEMP_STATE_PROGRAM
                
    def read_air_sensor_type(self):
        """Reports airsensor type"""
        #1 local, 2 remote
        self.read_field('sensorsavaliable')

        if self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_INT_FLOOR:
            return 1
        elif self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_ONLY or self.sensorsavaliable == READ_SENSORS_AVALIABLE_EXT_FLOOR:
            return 2
        raise ValueError("sensorsavaliable field invalid")
            
    def read_air_temp(self):
        """Read the air temperature getting data from device if too old"""
        if read_air_sensor_type(self) == 1:
            return self.read_field('airtemp', self.max_age_temp)
        else:
            return self.read_field('remoteairtemp', self.max_age_temp)
        
    def read_time(self, maxage=0):
        """Readtime, getting from device if required"""
        return self.read_field('currenttime', maxage)
        
    ## External functions for setting data

    def set_heating_schedule(self, day, schedule):
        """Set heating schedule for a single day"""
        padschedule = self.heat_schedule.pad_schedule(schedule)
        self.set_field(day, padschedule)

    def set_time(self):
        """set time on device to match current localtime on server"""
        timenow = time.time() + 0.5 #allow a little time for any delay in setting
        return self.set_field('currenttime', self.currenttime.localtimearray(timenow))

    #overriding

    def set_temp(self, temp):
        """sets the temperature demand overriding the program."""
        #Believe it returns at next prog change.
        if self.read_field('tempholdmins') == 0: #check hold temp not applied
            return self.set_field('setroomtemp', temp)
        else:
            logging.warn("%i address, temp hold applied so won't set temp"%(self.address))

    def release_temp(self):
        """release setTemp back to the program, but only if temp isn't held for a time (holdTemp)."""
        if self.read_field('tempholdmins') == 0: #check hold temp not applied
            return self.set_field('tempholdmins', 0)
        else:
            logging.warn("%i address, temp hold applied so won't remove set temp"%(self.address))

    def hold_temp(self, minutes, temp):
        """sets the temperature demand overrding the program for a set time."""
        #Believe it then returns to program.
        self.set_field('setroomtemp', temp)
        return self.set_field('tempholdmins', minutes)
        #didn't stay on if did minutes followed by temp.
        
    def release_hold_temp(self):
        """release setTemp or holdTemp back to the program."""
        return self.set_field('tempholdmins', 0)
        
    def set_holiday(self, hours):
        """sets holiday up for a defined number of hours."""
        return self.set_field('holidayhours', hours)
    
    def release_holiday(self):
        """cancels holiday mode"""
        return self.set_field('holidayhours', 0)

    #onoffs

    def set_on(self):
        """Switch stat on"""
        return self.set_field('onoff', WRITE_ONOFF_ON)
    def set_off(self):
        """Switch stat off"""
        return self.set_field('onoff', WRITE_ONOFF_OFF)
        
    def set_heat(self):
        """Switch stat to follow heat program"""
        return self.set_field('runmode', WRITE_RUNMODE_HEATING)
    def set_frost(self):
        """Switch stat to frost only"""
        return self.set_field('runmode', WRITE_RUNMODE_FROST)
        
    def set_lock(self):
        """Lock keypad"""
        return self.set_field('keylock', WRITE_KEYLOCK_ON)
    def set_unlock(self):
        """Unlock keypad"""
        return self.set_field('keylock', WRITE_KEYLOCK_OFF)

class ThermoStatDay(ThermoStatWeek):
    """Device class for thermostats operating daily programmode
    Heatmiser prt_e_model."""
    
    def _buildfields(self):
        """add to list of fields"""
        super(ThermoStatDay, self)._buildfields()
        self.fields.extend([
            HeatmiserFieldHeat('mon_heat', 103, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('tues_heat', 115, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('wed_heat', 127, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('thurs_heat', 139, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('fri_heat', 151, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('sat_heat', 163, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM),
            HeatmiserFieldHeat('sun_heat', 175, [[0, 24], [0, 59], [5, 35]], MAX_AGE_MEDIUM)
        ])
        
        self.heat_schedule = SchedulerDayHeat()
 
class ThermoStatHotWaterWeek(ThermoStatWeek):
    """Device class for thermostats with hotwater operating weekly programmode
    Heatmiser prt_hw_model."""
    
    def __init__(self, adaptor, devicesettings, generalsettings={}):
        super(ThermoStatHotWaterWeek, self).__init__(adaptor, devicesettings, generalsettings)
        self._expected_model_number = 4
        self._set_expected_field_values()
        
        #thermostat specific
        self.is_hot_water = True
    
    def _buildfields(self):
        """add to list of fields"""
        super(ThermoStatHotWaterWeek, self)._buildfields()
        self.fields.extend([
            HeatmiserFieldHotWaterDemand('hotwaterdemand', 42, [0, 2], MAX_AGE_USHORT),  # read [0=off, 1=on],  write [0=as prog, 1=override on, 2=overide off]
            HeatmiserFieldWater('wday_water', 71, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),  # pairs,  on then off repeated,  hour,  min
            HeatmiserFieldWater('wend_water', 87, [[0, 24], [0, 59]], MAX_AGE_MEDIUM)
            #7day progamming
        ])
        
        self.water_schedule = SchedulerWeekWater()
        
    def display_water_schedule(self):
        """Prints water schedule to stdout"""
        if not self.water_schedule is None:
            self.water_schedule.display()
            
    ### UNTESTED # last part about scheduletarget doesn't work
    def read_water_state(self):
        """Returns the current hot water control state from off to following program"""
        #does runmode affect hot water state?
        self.read_fields(['mon_water', 'tues_water', 'wed_water', 'thurs_water', 'fri_water', 'wday_water', 'wend_water'], -1)
        self.read_fields(['onoff', 'holidayhours', 'hotwaterdemand'])
        
        if self.onoff == WRITE_ONOFF_OFF:
            return self.TEMP_STATE_OFF
        elif self.holidayhours != 0:
            return self.TEMP_STATE_HOLIDAY
        else:
        
            if not self.currenttime.check_data_fresh(MAX_AGE_MEDIUM):
                self.read_time()
            
            locatimenow = self.currenttime.localtimearray()
            scheduletarget = self.water_schedule.get_current_schedule_item(locatimenow)

            if scheduletarget[SCH_ENT_TEMP] != self.hotwaterdemand:
                return self.TEMP_STATE_OVERRIDDEN
            else:
                return self.TEMP_STATE_PROGRAM
                
    def set_water_schedule(self, day, schedule):
        """Set water schedule for a single day"""
        padschedule = self.water_schedule.pad_schedule(schedule)
        if day == 'all':
            self.set_field('mon_water', padschedule)
            self.set_field('tues_water', padschedule)
            self.set_field('wed_water', padschedule)
            self.set_field('thurs_water', padschedule)
            self.set_field('fri_water', padschedule)
            self.set_field('sat_water', padschedule)
            self.set_field('sun_water', padschedule)
        else:
            self.set_field(day, padschedule)
    
class ThermoStatHotWaterDay(ThermoStatDay, ThermoStatHotWaterWeek):
    """Device class for thermostats with hotwater operating daily programmode
    Heatmiser prt_hw_model."""
    
    def _buildfields(self):
        """add to list of fields"""
        super(ThermoStatHotWaterDay, self)._buildfields()
        self.fields.extend([
            #7day progamming
            HeatmiserFieldWater('mon_water', 187, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('tues_water', 203, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('wed_water', 219, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('thurs_water', 235, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('fri_water', 251, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('sat_water', 267, [[0, 24], [0, 59]], MAX_AGE_MEDIUM),
            HeatmiserFieldWater('sun_water', 283, [[0, 24], [0, 59]], MAX_AGE_MEDIUM)
        ])
        self.water_schedule = SchedulerDayWater()
        
#other
#set floor limit

class HeatmiserUnknownDevice(HeatmiserDevice):
    """Device class for unknown thermostats"""
    
    def _update_settings(self, settings, generalsettings):
        """Check settings and get network data if needed"""

        self._load_settings(settings, generalsettings)
        
        # some basic config required before reading fields
        self._uniquetodcb = range(MAX_UNIQUE_ADDRESS + 1)
        self.rawdata = [None] * (MAX_UNIQUE_ADDRESS + 1)
        # assume fullreadtime is the worst case
        self.fullreadtime = self._estimate_read_time(MAX_UNIQUE_ADDRESS) 
        # use fields from device rather to set the expected mode and type
        self.read_fields(['model', 'programmode'], 0)
        self.expected_model = DEVICE_MODELS.keys()[DEVICE_MODELS.values().index(self.model.value)]
        self.expected_prog_mode = PROG_MODES.keys()[PROG_MODES.values().index(self.programmode.value)]
        
        self._process_settings()

class HeatmiserBroadcastDevice(HeatmiserDevice):
    """Broadcast device class for broadcast set functions and managing reading on all devices"""
    #List wrapper used to provide arguement to dectorator
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
    def read_field(self, fieldname, maxage=None):
        logging.info("All reading %s from %i controllers"%(fieldname, len(self._controllerlist.list)))
            
    @run_function_on_all(_controllerlist)
    def read_fields(self, fieldnames, maxage=None):
        logging.info("All reading %s from %i controllers"%(csvlist(fieldnames), len(self._controllerlist.list)))
        
    @run_function_on_all(_controllerlist)
    def read_air_temp(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def read_temp_state(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def read_water_state(self):
        pass
    
    @run_function_on_all(_controllerlist)
    def read_air_sensor_type(self):
        pass
            
    @run_function_on_all(_controllerlist)
    def read_time(self, maxage=0):
        pass
    
    #run set functions which require a read on all stats
    @run_function_on_all(_controllerlist)
    def set_temp(self, temp):
        pass
    
    @run_function_on_all(_controllerlist)
    def release_temp(self):
        pass
