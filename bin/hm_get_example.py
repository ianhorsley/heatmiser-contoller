#!/usr/bin/env python
"""Gets data from Heatmiser stats repeatedly and displays
Ian Horsley 2018
"""

import time
import logging

from heatmisercontroller.logging_setup import initialize_logger
from heatmisercontroller.hm_constants import *
from heatmisercontroller.network import HeatmiserNetwork
from heatmisercontroller.exceptions import HeatmiserResponseError

#start logging
initialize_logger('logs', logging.INFO, True)

HMN = HeatmiserNetwork()

# CYCLE THROUGH ALL CONTROLLERS
for current_controller in HMN.controllers:
    print "\r\nGetting all data control %2d in %s *****************************" %(current_controller.address, current_controller._long_name)

    try:
        current_controller.readAll()
    except HeatmiserResponseError as err:
        print "C%d in %s Failed to Read due to %s" %(current_controller.address, current_controller._name.ljust(4), str(err))
    else:
        disptext = "C%d Air Temp is %.1f from type %.f and Target set to %d    Boiler Demand %d" % (current_controller.address, current_controller.readAirTemp(), current_controller.readAirSensorType(), current_controller.setroomtemp, current_controller.heatingdemand)
        if current_controller.isHotWater():
            print "%s Hot Water Demand %d" %(disptext, current_controller.hotwaterdemand)
        else:
            print disptext
        current_controller.display_heating_schedule()
        current_controller.display_water_schedule()

time.sleep(5) # sleep before next cycle

#list fields used in following loop
SCHEDULEFIELDS = ['mon_heat', 'tues_heat', 'wed_heat', 'thurs_heat', 'fri_heat', 'wday_heat', 'wend_heat']
STATEFIELDS = ['onoff', 'frostprot', 'holidayhours', 'runmode', 'tempholdmins', 'setroomtemp']
OTHERFIELDS = ['sensorsavaliable', 'airtemp', 'remoteairtemp', 'heatingdemand', 'hotwaterdemand']
FIELDNAMES = STATEFIELDS + OTHERFIELDS

# CYCLE THROUGH ALL CONTROLLERS repeatedly, constantly updating parameters
while True:
    print
    for current_controller in HMN.controllers:
        try:
            #read all fields at the same time allows for most efficient number of reads
            current_controller.readFields(SCHEDULEFIELDS)
            current_controller.readFields(FIELDNAMES, 0) #force get on these fields
        except HeatmiserResponseError as err:
            print "C%d in %s Failed to Read due to %s" %(current_controller.address, current_controller._name.ljust(4), str(err))
        else:
            targettext = current_controller.printTarget()
            disptext = "C%d in %s Air Temp is %.1f from type %.f, %s, Heat %d" %(current_controller.address, current_controller._name.ljust(4), current_controller.readAirTemp(), current_controller.readAirSensorType(), targettext, current_controller.heatingdemand)

            if current_controller.isHotWater():
                print "%s Water %d" % (disptext, current_controller.hotwaterdemand)
            else:
                print disptext

    time.sleep(5) # sleep before next cycle

