#
# Ian Horsley 2018

#
# Heatmiser_Adaptor Class and helper functions
# handles serial connection and basic framing for the heatmiser protocol

# Assume Python 2.7.x
#

import time
import logging

from hm_constants import *
from comms_settings import *
import framing

from .exceptions import hmResponseError, hmResponseErrorCRC

# Master Address
MY_MASTER_ADDR = 0x81
    
def retryer(max_retries=3):
  def wraps(func):

      def inner(*args, **kwargs):
          for i in range(max_retries):
              if i is not 0:
                logging.warn("Gen retrying due to %s"%str(lasterror))
              try:    
                  result = func(*args, **kwargs)
              except hmResponseError as e:
                  lasterror = e
                  continue
              else:
                  return result
          else:
              raise hmResponseError("Failed after %i retries on %s"%(max_retries,str(lasterror))) 
      return inner
  return wraps
    
class Heatmiser_Adaptor:

  def __init__(self):
    
    self.serport = serial.Serial()
    self.serport.port = COM_PORT
    self.serport.baudrate = COM_BAUD
    self.serport.bytesize = COM_SIZE
    self.serport.parity = COM_PARITY
    self.serport.stopbits = COM_STOP
    self.serport.timeout = COM_TIMEOUT
    self.serport.write_timeout = COM_TIMEOUT
    
    self.COM_TIMEOUT = COM_TIMEOUT
    self.COM_START_TIMEOUT = COM_START_TIMEOUT
    
    self.lastsendtime = None
    self.creationtime = time.time()
    
    self.lastreceivetime = time.time() - COM_BUS_RESET_TIME # so that system will get on with sending straight away
    
    self.write_max_retries = 3
    self.read_max_retries = 3
    
  def __del__(self):
    self._disconnect()
    
### low level serial commands

  def connect(self):
    if not self.serport.isOpen():
      try:
        self.serport.open()
      except serial.SerialException as e:
        logging.error("Could not open serial port %s: %s" % (self.serport.portstr, e))
        raise

      logging.info("Gen %s port opened"% (self.serport.portstr))
      logging.debug("Gen %s baud, %s bit, %s parity, with %s stopbits, timeout %s seconds" % (self.serport.baudrate, self.serport.bytesize, self.serport.parity, self.serport.stopbits, self.serport.timeout))
    else:
      logging.warn("Gen serial port was already open")
    
  def _disconnect(self):
    #check if serial port is open and if so close
    #shouldn't need to call because handled by destructor
    if self.serport.isOpen():
      self.serport.close() # close port
      logging.info("Gen serial port closed")
    else:
      logging.warn("Gen serial port was already closed")
      
  def _hmSendMsg(self, message) :
      if not self.serport.isOpen():
        self.connect()

      #check time since last received to make sure bus has settled.
      waittime = COM_BUS_RESET_TIME - (time.time() - self.lastreceivetime)
      if waittime > 0:
        logging.debug("Gen waiting before sending %.2f"% ( waittime ))
        time.sleep(waittime)
      
      # http://stackoverflow.com/questions/180606/how-do-i-convert-a-list-of-ascii-values-to-a-string-in-python
      string = ''.join(map(chr,message))

      try:
        written = self.serport.write(string)  # Write a string
      except serial.SerialTimeoutException as e:
        self.serport.close() #need to close so that isOpen works correctly.
        logging.warning("Write timeout error: %s, sending %s" % (e, ', '.join(str(x) for x in message)))
        raise
      except serial.SerialException as e:
        self.serport.close() #need to close so that isOpen works correctly.
        logging.warning("Write error: %s, sending %s" % (e,  ', '.join(str(x) for x in message)))
        raise
      else:
        self.lastsendtime = time.strftime("%d %b %Y %H:%M:%S +0000", time.localtime(time.time())) #timezone is wrong
        logging.debug("Gen sent %s",', '.join(str(x) for x in message))

  def _hmClearInputBuffer(self):
    #clears input buffer
    #use after CRC check wrong; encase more data was sent than expected.
  
    time.sleep(self.COM_TIMEOUT) #wait for read timeout to ensure slave finished sending
    try:
      if self.serport.isOpen():
        self.serport.reset_input_buffer() #reset input buffer and dump any contents
      logging.warning("Input buffer cleared")
    except serial.SerialException as e:
      self.serport.close()
      logging.warning("Failed to clear input buffer")
      raise
          
  def _hmReceiveMsg(self, length = MAX_FRAME_RESP_LENGTH) :
      # Listen for a reply
      if not self.serport.isOpen():
        self.connect()
      logging.debug("Gen listening for %d"%length)
      
      # Listen for the first byte
      timereadstart = time.time()
      self.serport.timeout = self.COM_START_TIMEOUT #wait for start of response
      try:
        firstbyteread = self.serport.read(1)
      except serial.SerialException as e:
        #There is no new data from serial port (or port missing) (Doesn't include no response from stat)
        logging.warning("Gen serial port error: %s" % str(e))
        self.serport.close()
        raise
      else:
        timereadfirstbyte = time.time()-timereadstart
        logging.debug("Gen waited %.2fs for first byte"%timereadfirstbyte)
        if len(firstbyteread) == 0:
          raise hmResponseError("No Response")
        
        # Listen for the rest of the response
        self.serport.timeout = max(COM_MIN_TIMEOUT, self.COM_TIMEOUT - timereadfirstbyte) #wait for full time out for rest of response, but not less than COM_MIN_TIMEOUT)
        try:
          byteread = self.serport.read(length - 1)
        except serial.SerialException as e:
          #There is no new data from serial port (or port missing) (Doesn't include no response from stat)
          logging.warning("Gen serial port error: %s" % str(e))
          self.serport.close()
          raise

        #Convert back to array
        data = map(ord,firstbyteread) + map(ord,byteread)

        return data
      finally:
        self.serport.timeout = self.COM_TIMEOUT #make sure timeout is reverted
        self.lastreceivetime = time.time() #record last read time. Used to manage bus settling.

### protocol functions
  
  @retryer(max_retries = 3)
  def hmWriteToController(self, network_address, protocol, dcb_address, length, payload):
      ###shouldn't be labelled dcb_address. It is a unique address.
      msg = framing._hmFormFrame(network_address, protocol, MY_MASTER_ADDR, FUNC_WRITE, dcb_address, length, payload)
      
      try:
        self._hmSendMsg(msg)
      except Exception as e:
        logging.warn("C%i writing to address, no message sent"%(network_address))
        raise
      else:
        logging.debug("C%i written to address %i length %i payload %s"%(network_address,dcb_address, length, ', '.join(str(x) for x in payload)))
        if network_address == BROADCAST_ADDR:
          self.lastreceivetime = time.time() + COM_SEND_MIN_TIME - COM_BUS_RESET_TIME # if broadcasting force it to wait longer until next send
        else:
          response = self._hmReceiveMsg(FRAME_WRITE_RESP_LENGTH)
          try:
            framing._hmVerifyWriteAck(protocol, network_address, MY_MASTER_ADDR, response)
          except hmResponseErrorCRC:
            self._hmClearInputBuffer()
            raise
  
  @retryer(max_retries = 2)
  def hmReadFromController(self, network_address, protocol, dcb_start_address, expectedLength, readall = False):
    ###mis labelled dcb addres, should be unique
      if readall:
        msg = framing._hmFormReadFrame(network_address, protocol, MY_MASTER_ADDR, DCB_START, RW_LENGTH_ALL)
        logging.debug("C %i read request to address %i length %i"%(network_address,DCB_START, RW_LENGTH_ALL))
      else:
        msg = framing._hmFormReadFrame(network_address, protocol, MY_MASTER_ADDR, dcb_start_address, expectedLength)
        logging.debug("C %i read request to address %i length %i"%(network_address,dcb_start_address, expectedLength))
      
      try:
        self._hmSendMsg(msg)
      except:
        logging.warn("C%i address, read message not sent"%(network_address))
        raise
      else:
        time1 = time.time()

        try:
          response = self._hmReceiveMsg(MIN_FRAME_READ_RESP_LENGTH + expectedLength)
        except Exception as e:
          logging.warn("C%i read failed from address %i length %i due to %s"%(network_address,dcb_start_address, expectedLength, str(e)))
          raise
        else:
          logging.debug("C%i read in %.2f s from address %i length %i response %s"%(network_address,time.time()-time1,dcb_start_address, expectedLength, ', '.join(str(x) for x in response)))
        
          try:
            framing._hmVerifyResponse(protocol, network_address, MY_MASTER_ADDR, FUNC_READ, expectedLength , response)
          except hmResponseErrorCRC:
            self._hmClearInputBuffer()
            raise
          return response[FR_CONTENTS:-CRC_LENGTH]

  def hmReadAllFromController(self, network_address, protocol, expectedLength):
      return self.hmReadFromController(network_address, protocol, DCB_START, expectedLength, True)

  def hmSetField(self, network_address, protocol, fieldname,state) :
      #set a field to a state. Defined for single or double length fields
      fieldinfo = uniadd[fieldname]
      
      if not isinstance(state, (int, long)) or state < fieldinfo[UNIADD_RANGE][0] or state > fieldinfo[UNIADD_RANGE][1]:
        raise ValueError("hmSetField: invalid requested value")
      elif fieldinfo[UNIADD_LEN] != 1 and fieldinfo[UNIADD_LEN] != 2 :
        raise ValueError("hmSetField: field isn't single or dual")
      elif len(fieldinfo) < UNIADD_WRITE + 1 or fieldinfo[UNIADD_WRITE] != 'W':
        raise ValueError("hmSetField: field isn't writeable")
      
      if network_address == BROADCAST_ADDR or protocol == HMV3_ID:
        if fieldinfo[UNIADD_LEN] == 1:
          payload = [state]
        else:
          pay_lo = (state & BYTEMASK)
          pay_hi = (state >> 8) & BYTEMASK
          payload = [pay_lo, pay_hi]
        try:
          self.hmWriteToController(network_address, protocol, fieldinfo[UNIADD_ADD], fieldinfo[UNIADD_LEN], payload)
        except:
          logging.info("C%i failed to set field %s to %i"%(network_address, fieldname.ljust(FIELD_NAME_LENGTH), state))
          raise
        else:
          logging.info("C%i set field %s to %i"%(network_address, fieldname.ljust(FIELD_NAME_LENGTH), state))
      else:
        raise ValueError("Un-supported protocol found %s" % protocol)

          
  def hmSetFields(self, network_address,protocol,uniqueaddress,payload) :
      #set a field to a state. Defined for fields greater than 2 in length
      fieldinfo = uniadd[uniqueaddress]
      
      if len(payload) != fieldinfo[UNIADD_LEN]:
        raise ValueError("hmSetFields: invalid payload length")
      elif fieldinfo[UNIADD_LEN] <= 2:
        raise ValueError("hmSetFields: field isn't array")
      elif fieldinfo[UNIADD_WRITE] != 'W':
        raise ValueError("hmSetFields: field isn't writeable")
      self._checkPayloadValues(payload, fieldinfo[UNIADD_RANGE])
      
      ###could add payload padding
      #payloadgrouped=chunks(payload,len(fieldinfo[UNIADD_RANGE]))
      
      if network_address == BROADCAST_ADDR or protocol == HMV3_ID:
        try :
          self.hmWriteToController(network_address, protocol, fieldinfo[UNIADD_ADD], len(payload), payload)
        except:
          logging.debug("C%i failed to set field %s to %s"%(network_address, uniqueaddress.ljust(FIELD_NAME_LENGTH), ', '.join(str(x) for x in payload)))
          raise
        else:
          logging.info("C%i Set field %s to %s"%(network_address, uniqueaddress.ljust(FIELD_NAME_LENGTH), ', '.join(str(x) for x in payload)))
      else:
        raise ValueError("Un-supported protocol found %s" % protocol)

  def _checkPayloadValues(self, payload, ranges):
    #checks the payload matches the ranges if ranges are defined
    if ranges != []:
      for i, item in enumerate(payload):
        range = ranges[i % len(ranges)]
        if item < range[0] or item > range[1]:
          ValueError("hmSetFields: payload out of range")

  ## Shouldn't be here move to controllers
  def hmUpdateTime(self, network_address) :
      """bla bla"""
      #protocol = HMV3_ID # TODO should look this up in statlist
      #if protocol == HMV3_ID:
      msgtime = time.time()
      msgtimet = time.localtime(msgtime)
      day  = int(time.strftime("%w", msgtimet))
      if (day == 0):
          day = 7		# Convert python day format to Heatmiser format
      hour = int(time.strftime("%H", msgtimet))
      mins = int(time.strftime("%M", msgtimet))
      secs = int(time.strftime("%S", msgtimet))
      if (secs == 61):
          secs = 60 # Need to do this as pyhton seconds can be  [0,61]
      print "%d %d:%d:%d" % (day, hour, mins, secs)
      payload = [day, hour, mins, secs]
          
      return self.hmSetFields(network_address,'currenttime',payload)

