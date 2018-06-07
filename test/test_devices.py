import unittest
import logging
import time

from heatmisercontroller.devices import hmController
from heatmisercontroller.hm_constants import HMV3_ID, PRT_E_MODEL, PRT_HW_MODEL, PROG_MODE_DAY, DCB_INVALID
from heatmisercontroller.exceptions import hmResponseError, hmControllerTimeError

class test_reading_data(unittest.TestCase):
  def setUp(self):
    logging.basicConfig(level=logging.ERROR)
    #network, address, protocol, short_name, long_name, model, mode
    #self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
      
  def test_procfield(self):
    #unique_address,length,divisor, valid range
    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
    self.func._procfield([1],'test',[0, 1, 1, []])
    self.func._procfield([1],'test',[0, 1, 1, [0, 1]])
    self.func._procfield([1, 1],'test',[0, 2, 1, [0, 257]])
    self.func._procfield([PRT_HW_MODEL],'model',[0, 1, 1, []])
    self.func._procfield([PROG_MODE_DAY],'programmode',[0, 1, 1, []])
    
  def test_procfield_range(self):
    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
    with self.assertRaises(hmResponseError):
      self.func._procfield([3],'test',[0, 1, 1, [0, 1]])
      
  def test_procfield_model(self):
    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
    with self.assertRaises(hmResponseError):
      self.func._procfield([3],'model',[0, 1, 1, []])
    
  def test_procpayload(self):
    goodmessage = [1, 37, 0, 22, 4, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 38, 1, 9, 12, 28, 1, 1, 0, 0, 0, 0, 0, 0, 255, 255, 255, 255, 0, 220, 0, 0, 0, 3, 14, 49, 36, 7, 0, 19, 9, 30, 10, 17, 0, 19, 21, 30, 10, 7, 0, 19, 21, 30, 10, 24, 0, 5, 24, 0, 5, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 8, 0, 9, 0, 18, 0, 19, 0, 24, 0, 24, 0, 24, 0, 24, 0, 7, 0, 20, 21, 30, 12, 24, 0, 12, 24, 0, 12, 7, 0, 20, 21, 30, 12, 24, 0, 12, 24, 0, 12, 7, 0, 19, 8, 30, 12, 16, 30, 20, 21, 0, 12, 7, 0, 20, 12, 0, 12, 17, 0, 20, 21, 30, 12, 5, 0, 20, 21, 30, 12, 24, 0, 12, 24, 0, 12, 7, 0, 20, 12, 0, 12, 17, 0, 20, 21, 30, 12, 7, 0, 12, 24, 0, 12, 24, 0, 12, 24, 0, 12, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 17, 30, 18, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0, 24, 0]

    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
    self.func.lastreadtime = 6 * 86400 + 53376.0 - 3600
    self.func._procpayload(goodmessage)

  def test_readall(self):
    pass

class test_other_functions(unittest.TestCase):
  def test_getDCBaddress(self):
    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_E_MODEL, PROG_MODE_DAY)
    self.assertEqual(0, self.func._getDCBaddress(0))
    self.assertEqual(24, self.func._getDCBaddress(24))
    self.assertEqual(DCB_INVALID, self.func._getDCBaddress(26))
  
class test_time_functions(unittest.TestCase):
  def setUp(self):
    #gettimezone offset
    is_dst = time.daylight and time.localtime().tm_isdst > 0
    self.utc_offset = - (time.altzone if is_dst else time.timezone)
    self.func = hmController(None, 1, HMV3_ID, 'test', 'test controller', PRT_HW_MODEL, PROG_MODE_DAY)
    
  def test_checkcontrollertime_none(self):
    with self.assertRaises(hmResponseError):
      self.func._checkcontrollertime()
  def test_checkcontrollertime_bad(self):
    self.func.datareadtime['currenttime'] = ( 1 + 3) * 86400 + 9 * 3600 + 33 * 60 + 0 - self.utc_offset #has been read 
    self.func.data['currenttime'] = self.func.currenttime = [1, 0, 0, 0]
    with self.assertRaises(hmControllerTimeError):
      self.func._checkcontrollertime()
    
  def test_checkcontrollertime_1(self):
    self.func.datareadtime['currenttime'] = ( 4 + 3) * 86400 + 9 * 3600 + 33 * 60 + 5 - self.utc_offset #has been read 
    self.func.data['currenttime'] = self.func.currenttime = [4, 9, 33, 0]
    self.func._checkcontrollertime()
    self.assertEqual(5, self.func.timeerr)
    
  def test_checkcontrollertime_2(self):
    self.func.datareadtime['currenttime'] = ( 7 + 3) * 86400 + 23 * 3600 + 59 * 60 + 55 - self.utc_offset #has been read 
    self.func.data['currenttime'] = self.func.currenttime = [1, 0, 0, 0]
    self.func._checkcontrollertime()
    self.assertEqual(5, self.func.timeerr)

  def test_localtimearray(self):
    self.assertEqual([4, 6, 48, 47], self.func._localtimearray(1528350527))
    self.assertEqual([7, 6, 48, 47], self.func._localtimearray(1528350527-86400*4))
  
  
if __name__ == '__main__':
    unittest.main()

