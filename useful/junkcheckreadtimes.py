#!/usr/bin/env python
"""Script to time the responses from the stats for different read lengths"""
from timeit import default_timer as timer
import logging
import numpy as np

from heatmisercontroller.logging_setup import initialize_logger_full
from heatmisercontroller.hm_constants import HMV3_ID, fields, FIELD_ADD, FIELD_NAME
from heatmisercontroller.network import HeatmiserNetwork
from heatmisercontroller.exceptions import HeatmiserResponseError

initialize_logger_full('logs', logging.WARN)
HMN = HeatmiserNetwork()

STAT = HMN.Kit
ADDRESS = STAT.address
DCBLEN = STAT.dcb_length

field = 'tempholdmins' #Kit
#field = 'currenttime' #Others
#field = 'mon_heat' #Others on day

#print STAT._getFieldBlocks('DCBlen','sun_water')
print(STAT.dcb_length)

def testall():
    print("All No proc")
    times = []
    for _ in range(TESTS):
        try:
            start = timer()
            HMN.adaptor.read_all_from_device(ADDRESS, HMV3_ID, DCBLEN)
            times.append(timer() - start - HMN.adaptor.serport.COM_BUS_RESET_TIME) 
        except HeatmiserResponseError:
            print("errored")
            time.sleep(5)
    print("%.3f"%np.median(times), len(times))

def test(number):
    print("%i No proc"%number)
    times = []
    for _ in range(TESTS):
        try:
            start = timer()
            HMN.adaptor.read_from_device(ADDRESS, HMV3_ID, fields[fieldnametonum[field]][FIELD_ADD], number)
            times.append(timer() - start - HMN.adaptor.serport.COM_BUS_RESET_TIME) 
        except HeatmiserResponseError:
            print("errored")
    print("%.3f"%np.median(times), len(times))

fieldnametonum = {}
for key, data in enumerate(fields):
    fieldname = data[FIELD_NAME]
    fieldnametonum[fieldname] = key

TESTS = 30
CASES = [1, 150, 200, 250]
for i in CASES:
    test(i)
testall()
