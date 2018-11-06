from transitions import Machine

class Thermostat(object):

    states = [ { 'name': 'off', 'on_enter': 'thres_off' },
            { 'name': 'offfrost', 'on_enter': 'thres_frost' },
            { 'name': 'frost', 'on_enter': 'thres_frost' },
            { 'name': 'setpoint', 'on_enter': 'thres_setpoint' }
            ]
    
    def thres_off(self, arg=None):
        print "STATE off"
        self.threshold = None
        
    def thres_setpoint(self, arg=None):
        print "STATE to setpoint ", self.setroomtemp
        self.threshold = self.setroomtemp
    
    def thres_frost(self, arg=None):
        print "STATE to", self.state
        self.threshold = self.frosttemp
    
    def cond_frost(self, arg=None):
        return self.holidayhours.is_value('OFF') and self.runmode.is_value('HEAT')

    def cond_on(self, arg=None):
        return self.onoff.is_value('ON')
        
    def cond_frostprocdisable(self, arg=None):
        return self.frostprocdisable.is_value('ON')
       
    def __init__(self, name):
    
        self.name = name
        self.threshold = None
        self.frosttemp = None #point to field value
        self.frostprocdisable = None # point to field value
        self.runmode = None #point to field value
        self.setroomtemp = None
        self.onoff = None
        
        self.machine = Machine(model=self, states=Thermostat.states, initial='off')
        
        self.machine.add_transition('switch_off', ['frost', 'setpoint'], 'off', conditions='cond_frostprocdisable')
        self.machine.add_transition('switch_off', ['frost', 'setpoint'], 'offfrost', unless='cond_frostprocdisable')
        self.machine.add_transition('switch_off', 'offfrost', 'off', conditions='cond_frostprocdisable')
        self.machine.add_transition('switch_off', 'off', 'offfrost', unless='cond_frostprocdisable')
        
        #self.machine.add_transition('switch_on', ['off', 'offfrost'], 'setpoint', conditions='cond_frost')
        #self.machine.add_transition('switch_on', ['off', 'offfrost'], 'frost', unless='cond_frost')
        
        self.machine.add_transition('switch_swap', '*', 'setpoint', conditions=['cond_frost','cond_on'])
        self.machine.add_transition('switch_swap', ['off', 'offfrost', 'setpoint'], 'frost', conditions='cond_on', unless='cond_frost')
        