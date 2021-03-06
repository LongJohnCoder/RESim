'''
 * This software was created by United States Government employees
 * and may not be copyrighted.
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT,
 * INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
 * STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
'''

from simics import *
import logging
'''
Manage cycle events to limit how far a session can run without some intervening event.
'''
class BackStop():
    def cycle_handler(self, obj, cycles):
        if self.back_stop_cycle is None:
            return
        self.lgr.debug("backStop, cycle_handler ")
        if self.cpu is not None:
            self.lgr.debug('backStop cycle_handler going to break simuation cpu is %s cycles: 0x%x' % (self.cpu.name, self.cpu.cycles))
            self.clearCycle()
            SIM_break_simulation('hit final cycle')
            if self.callback is not None:
                self.callback()
        else: 
            self.lgr.debug('backStop cycle_handler lingering after cpu set to None, ignore')
            SIM_continue(0)
        #SIM_run_alone(self.runalone_callback, None)
       
        #SIM_event_post_cycle(obj, cycle_event, obj, cycles, cycles)
 

    def __init__(self, cpu, lgr=None):
        if lgr is None:
            self.lgr = logging
        else:
            self.lgr = lgr
        self.cycle_event = None 
        self.cpu = cpu
        self.callback = None
        self.lgr.debug('backStop init cpu %s' % self.cpu.name)

    def setCallback(self, callback):
        self.callback = callback

    def clearCycle(self):
        if self.cycle_event is not None:
            self.lgr.debug('backStop clearCycle')
            #SIM_event_cancel_time(cpu, self.cycle_event, self.cpu, 0, None)
            SIM_event_cancel_time(self.cpu, self.cycle_event, self.cpu, None, None)
        self.back_stop_cycle = None

    def setFutureCycleAlone(self, cycles):
        if self.cycle_event is None:
            self.cycle_event = SIM_register_event("cycle event", SIM_get_class("sim"), Sim_EC_Notsaved, self.cycle_handler, None, None, None, None)
        else:
            SIM_event_cancel_time(self.cpu, self.cycle_event, self.cpu, None, None)
        self.back_stop_cycle = self.cpu.cycles + cycles
        SIM_event_post_cycle(self.cpu, self.cycle_event, self.cpu, cycles, cycles)
        self.lgr.debug('backStop setFuturecycleAlone, now: 0x%x  cycles: 0x%x' % (self.cpu.cycles, cycles))

    def setFutureCycle(self, cycles):
        SIM_run_alone(self.setFutureCycleAlone, cycles)

if __name__ == "__main__":
    bs = backStop()
 
