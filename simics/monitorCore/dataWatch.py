from simics import *
import pageUtils
import stopFunction
import hapCleaner
import decode
import decodeArm
import elfText
import memUtils
import watchMarks
import backStop
from stackTrace import mem_funs
import os
class DataWatch():
    ''' Watch a range of memory and stop when it is read.  Intended for use in tracking
        reads to buffers into which data has been read, e.g., via RECV. '''
    def __init__(self, top, cpu, page_size, context_manager, mem_utils, param, lgr):
        ''' data watch structures reflecting what we are watching '''
        self.start = []
        self.length = []
        self.cycle = []
        self.read_hap = []
        self.top = top
        self.cpu = cpu
        self.context_manager = context_manager
        self.mem_utils = mem_utils
        self.lgr = lgr
        self.page_size = page_size
        self.show_cmp = False
        self.break_simulation = True
        self.param = param
        self.return_break = None
        self.return_hap = None
        self.prev_cycle = None
        self.ida_funs = None
        self.relocatables = None
        self.user_iterators = None
        self.back_stop = backStop.BackStop(self.cpu, self.lgr)
        self.watchMarks = watchMarks.WatchMarks(mem_utils, cpu, lgr)
        back_stop_string = os.getenv('BACK_STOP_CYCLES')
        if back_stop_string is None:
            self.back_stop_cycles = 5000000
        else:
            self.back_stop_cycles = int(back_stop_string)
        ''' Do not set backstop until first read, otherwise accept followed by writes will trigger it. '''
        self.use_back_stop = False
        
        lgr.debug('DataWatch init with back_stop_cycles %d' % self.back_stop_cycles)
        if cpu.architecture == 'arm':
            self.decode = decodeArm
        else:
            self.decode = decode

    def setRange(self, start, length, msg=None, max_len=None, back_stop=True):
        self.lgr.debug('DataWatch set range start 0x%x length 0x%x' % (start, length))
        if not self.use_back_stop and back_stop:
            self.use_back_stop = True

        end = start+length
        overlap = False
        for index in range(len(self.start)):
            if self.start[index] != 0:
                this_end = self.start[index] + self.length[index]
                if self.start[index] <= start and this_end >= end:
                    overlap = True
                    self.lgr.debug('DataWatch setRange found overlap, skip it')
                    break
                elif self.start[index] >= start and this_end <= end:
                    self.lgr.debug('DataWatch setRange found subrange, replace it')
                    self.start[index] = start
                    self.length[index] = length
                    overlap = True
                    break
                elif start == (this_end+1):
                    self.length[index] = self.length[index]+length
                    overlap = True
                    break
        if not overlap:
            self.start.append(start)
            self.length.append(length)
            self.cycle.append(self.cpu.cycles)
        if msg is not None:
            fixed = unicode(msg, errors='replace')
            self.watchMarks.markCall(fixed, max_len)

    def close(self, fd):
        ''' called when FD is closed and we might be doing a trackIO '''
        eip = self.top.getEIP(self.cpu)
        msg = 'closed FD: %d' % fd
        self.watchMarks.markCall(msg, None)
        

    def watch(self, show_cmp=False, break_simulation=None):
        self.lgr.debug('DataWatch watch show_cmp: %r cpu: %s' % (show_cmp, self.cpu.name))
        self.show_cmp = show_cmp         
        if break_simulation is not None:
            self.break_simulation = break_simulation         
        if len(self.start) > 0:
            self.setBreakRange()
            return True
        return False

    def showCmp(self, addr): 
        eip = self.top.getEIP(self.cpu)
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        self.lgr.debug('showCmp eip 0x%x %s' % (eip, instruct[1]))
        mval = self.mem_utils.readWord32(self.cpu, addr)
        if instruct[1].startswith('cmp'):
            op2, op1 = self.decode.getOperands(instruct[1])
            val = None
            if self.decode.isReg(op2):
                val = self.mem_utils.getRegValue(self.cpu, op2)
            elif self.decode.isReg(op1):
                val = self.mem_utils.getRegValue(self.cpu, op1)
            if val is not None:
                print('%s  reg: 0x%x  addr:0x%x mval: 0x%08x' % (instruct[1], val, addr, mval))
          
    def getCmp(self):
        retval = '' 
        eip = self.top.getEIP(self.cpu)
        for i in range(10):
            instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
            if instruct[1].startswith('cmp'):
                retval = instruct[1]
                break
            else:
                eip = eip + instruct[0]
        return retval
            
               
    def stopWatch(self, break_simulation=None): 
        self.lgr.debug('dataWatch stopWatch')
        for index in range(len(self.start)):
            if self.start[index] == 0:
                continue
            if index < len(self.read_hap):
                if self.read_hap[index] is not None:
                    self.context_manager.genDeleteHap(self.read_hap[index])
            else:
                self.lgr.debug('dataWatch stopWatch index %d not in read_hap len is %d ' % (index, len(self.read_hap)))
        del self.read_hap[:]
        if break_simulation is not None: 
            self.break_simulation = break_simulation
        if self.return_hap is not None:
            self.context_manager.genDeleteHap(self.return_hap)
            self.return_hap = None
      
        if self.back_stop is not None:
            self.back_stop.clearCycle()
    
    def kernelReturnHap(self, addr, third, forth, memory):
        self.context_manager.genDeleteHap(self.return_hap)
        eax = self.mem_utils.getRegValue(self.cpu, 'syscall_ret')
        self.lgr.debug('kernelReturnHap, retval 0x%x  addr: 0x%x' % (eax, addr))
        self.watchMarks.kernel(addr, eax)
        self.watch()

    def kernelReturn(self, addr):
        if self.cpu.architecture == 'arm':
            cell = self.top.getCell()
            proc_break = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.arm_ret, 1, 0)
            self.return_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.kernelReturnHap, addr, proc_break, 'memcpy_return_hap')
        else:
            self.lgr.debug('Only ARM kernel return handled for now') 
            self.watch()
       
    class MemSomething():
        def __init__(self, fun, ret_ip, src, dest, count): 
            self.fun = fun
            self.ret_ip = ret_ip
            self.src = src
            self.dest = dest
            self.count = count
      
    def returnHap(self, mem_something, third, forth, memory):
        if self.return_hap is None:
            return
        self.context_manager.genDeleteHap(self.return_hap)
        self.return_hap = None
        if mem_something.fun == 'memcpy' or mem_something.fun == 'mempcpy':
            self.lgr.debug('dataWatch returnHap, return from %s src: 0x%x dest: 0x%x count %d ' % (mem_something.fun, mem_something.src, 
                   mem_something.dest, mem_something.count))
            self.setRange(mem_something.dest, mem_something.count, None) 
            buf_start = self.findRange(mem_something.src)
            if buf_start is None:
                self.lgr.error('dataWatch buf_start for 0x%x is none?' % (mem_something.src))
            self.watchMarks.copy(mem_something.src, mem_something.dest, mem_something.count, buf_start)
        elif mem_something.fun == 'memcmp':
            buf_start = self.findRange(mem_something.dest)
            self.watchMarks.compare(mem_something.dest, mem_something.src, mem_something.count, buf_start)
            self.lgr.debug('dataWatch returnHap, return from %s compare: 0x%x  to: 0x%x count %d ' % (mem_something.fun, mem_something.src, 
                   mem_something.dest, mem_something.count))
        elif mem_something.fun == 'strcmp':
            buf_start = self.findRange(mem_something.dest)
            self.watchMarks.compare(mem_something.dest, mem_something.src, mem_something.count, buf_start)
            self.lgr.debug('dataWatch returnHap, return from %s strcmp: 0x%x  to: 0x%x count %d ' % (mem_something.fun, mem_something.src, 
                   mem_something.dest, mem_something.count))
        elif mem_something.fun == 'strcpy':
            self.lgr.debug('dataWatch returnHap, strcpy return from %s src: 0x%x dest: 0x%x count %d ' % (mem_something.fun, mem_something.src, 
                   mem_something.dest, mem_something.count))
            self.setRange(mem_something.dest, mem_something.count, None) 
            buf_start = self.findRange(mem_something.src)
            if buf_start is None:
                self.lgr.error('dataWatch buf_start for 0x%x is none?' % (mem_something.src))
            self.watchMarks.copy(mem_something.src, mem_something.dest, mem_something.count, buf_start)
        elif mem_something.fun == 'memset':
            self.setRange(0, 0, None) 
            self.lgr.debug('dataWatch returnHap, return from memset dest: 0x%x count %d ' % (mem_something.dest, mem_something.count))
            buf_start = self.findRange(mem_something.dest)
            self.watchMarks.memset(mem_something.dest, mem_something.count, buf_start)
        elif mem_something.fun not in mem_funs:
            ''' assume iterator '''
            self.lgr.debug('dataWatch returnHap, return from iterator %s src: 0x%x ' % (mem_something.fun, mem_something.src))
            buf_start = self.findRange(mem_something.src)
            self.watchMarks.iterator(mem_something.fun, mem_something.src, buf_start)
        else:
            self.lgr.error('dataWatch returnHap no handler for %s' % mem_something.fun)
        #SIM_break_simulation('return hap')
        #return
        self.watch()

    def walkAlone(self, mem_something):        
        if self.ida_funs is not None:
            self.top.stopThreadTrack()
            ''' Step backwards until we reach a call.  Assumes we start near the beginning of a mem function '''
            ip = self.top.getEIP(self.cpu)
            fun = self.ida_funs.getFun(ip)
            if fun is not None:
                self.lgr.debug('walkAlone, ip 0x%x, fun is %s' % (ip, fun))
            else:
                self.lgr.debug('walkAlone, ip 0x%x NO FUN')
            done = False
            bound = 0
            while not done:
                back_one = self.cpu.cycles-1
                cmd = 'skip-to cycle = %d ' % back_one
                SIM_run_command(cmd)
                pc = self.mem_utils.getRegValue(self.cpu, 'pc')
                instruct = SIM_disassemble_address(self.cpu, pc, 1, 0)
                self.lgr.debug('skipped to 0x%x, landed at 0x%x  pc: 0x%x instruct %s' % (back_one, self.cpu.cycles, pc, instruct[1]))
                if self.decode.isCall(self.cpu, instruct[1]):
                    parts = instruct[1].split()
                    call_to = parts[1]
                    try:
                        dest = int(call_to, 16)
                        if dest == fun:
                            done = True
                            self.lgr.debug('walkAlone found call to 0x%x' % fun)
                        elif dest in self.relocatables:
                            done = True
                            self.lgr.debug('walkAlone found relocatable call to %s' % self.relocatables[dest])
                        elif self.user_iterators.isIterator(dest, self.lgr):
                            done = True
                            self.lgr.debug('walkAlone found call to iterator 0x%x' % dest)
                        else: 
                            self.lgr.debug('walkAlone is call, but not to function containing PC 0x%x' % pc)
                    except ValueError:
                        pass
                bound += 1
                if bound > 50:
                    print('call not found all all that')
                    return
            
            self.top.startThreadTrack()
            self.lgr.debug('walkAlone, got call %s' % instruct[1])
            if mem_something.fun == 'memcpy' or mem_something.fun == 'memmove' or mem_something.fun == 'mempcpy': 
                mem_something.dest = self.mem_utils.getRegValue(self.cpu, 'r0')
                mem_something.count = self.mem_utils.getRegValue(self.cpu, 'r2')
                self.lgr.debug('dest 0x%x  src 0x%x count 0x%x' % (mem_something.dest, mem_something.src, mem_something.count))
            elif mem_something.fun == 'memset':
                mem_something.dest = self.mem_utils.getRegValue(self.cpu, 'r0')
                mem_something.src = None
            elif mem_something.fun == 'memcmp':
                mem_something.count = self.mem_utils.getRegValue(self.cpu, 'r2')
                mem_something.src = self.mem_utils.getRegValue(self.cpu, 'r0')
                mem_something.dest = self.mem_utils.getRegValue(self.cpu, 'r1')
            cell = self.top.getCell()
            proc_break = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, mem_something.ret_ip, 1, 0)
            self.return_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.returnHap, mem_something, proc_break, 'memcpy_return_hap')
            self.lgr.debug('walkAlone set hap on ret_ip at 0x%x Now run!' % mem_something.ret_ip)
            SIM_run_command('c')
        else:
            self.lgr.debug('walkAlone, no ida functions')


    def runToReturnAlone(self, mem_something):
        cell = self.top.getCell()
        proc_break = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, mem_something.ret_ip, 1, 0)
        self.return_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.returnHap, mem_something, proc_break, 'memsomething_return_hap')

    def memstuffStopHap(self, mem_something, one, exception, error_string):
        if self.stop_hap is not None:
            self.lgr.debug('memstuffStopHap stopHap will delete hap %s' % str(self.stop_hap))
            SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.stop_hap)
            self.stop_hap = None
        if self.cpu.architecture == 'arm':
            self.lgr.debug('memstuffStopHap, walk back to a call')
            SIM_run_alone(self.walkAlone, mem_something)
        else:
            self.lgr.debug('Only ARM memcpy handled for now') 
            self.watch()

    def getStrLen(self, src):
        addr = src
        done = False
        self.lgr.debug('getStrLen from 0x%x' % src)
        while not done:
            v = self.mem_utils.readByte(self.cpu, addr)
            self.lgr.debug('getStrLen got 0x%x from 0x%x' % (v, addr))
            if v == 0:
                done = True
            else:
                addr += 1
        return addr - src

    def handleMemStuff(self, mem_something):
        '''
        We are within a memcpy type function for which we believe we know the calling conventions.  However those values have been
        lost to the vagaries of the implementation by the time we hit the breakpoint.  We need to stop; Reverse to the call; record the parameters;
        set a break on the return; and continue.  We'll assume not too many instructions between us and the call, so manually walk er back.
        '''
        self.lgr.debug('handleMemStuff ret_addr 0x%x fun %s' % (mem_something.ret_ip, mem_something.fun))
        if self.cpu.architecture == 'arm':
            if mem_something.fun == 'strcpy':
                mem_something.dest = self.mem_utils.getRegValue(self.cpu, 'r0')
                ''' TBD this fails on buffer overlap, but that leads to crash anyway? '''
                mem_something.count = self.getStrLen(mem_something.src)        
                self.lgr.debug('handleMemStuff strcpy, src: 0x%x dest: 0x%x count(maybe): %d' % (mem_something.src, mem_something.dest, mem_something.count))
                SIM_run_alone(self.runToReturnAlone, mem_something)
            elif mem_something.fun == 'strcmp':
                # the buffer string
                mem_something.dest = self.mem_utils.getRegValue(self.cpu, 'r0')
                mem_something.src = self.mem_utils.getRegValue(self.cpu, 'r1')
                mem_something.count = self.getStrLen(mem_something.src)        
                self.lgr.debug('handleMemStuff strcmp, src: 0x%x dest: 0x%x count(maybe): %d' % (mem_something.src, mem_something.dest, mem_something.count))
                SIM_run_alone(self.runToReturnAlone, mem_something)
            elif mem_something.fun not in mem_funs: 
                ''' assume it is a user iterator '''
                self.lgr.debug('handleMemStuff assume iterator, src: 0x%x ' % (mem_something.src))
                SIM_run_alone(self.runToReturnAlone, mem_something)
            else: 
                ''' walk backwards to the call, and get the parameters.  TBD, why not do same for strcpy and strcmp? '''
                self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
            	     self.memstuffStopHap, mem_something)
                SIM_break_simulation('handle memstuff')
            
        else:
            self.lgr.debug('Only ARM memcpy handled for now') 
            self.watch()

    def isMemSomething(self, eip):
        ''' TBD not used '''
        retval = False
        if self.ida_funs is not None:
            fun = self.ida_funs.getFun(eip)
            if fun is not None:
                fname = self.ida_funs.getName(fun) 
                if name.startswith('mem'):
                    retval = True
        return retval
            

    def readHap(self, index, third, forth, memory):
        ''' watched data has been read (or written) '''
        if self.cpu.cycles == self.prev_cycle:
            return
        if len(self.read_hap) == 0:
            return
        self.prev_cycle = self.cpu.cycles

        if self.back_stop is not None and not self.break_simulation and self.use_back_stop:
            self.back_stop.setFutureCycle(self.back_stop_cycles)
        if index >= len(self.read_hap):
            self.lgr.error('dataWatch readHap invalid index %d, only %d read haps' % (index, len(self.read_hap)))
            return
        if self.read_hap[index] is None:
            return
        op_type = SIM_get_mem_op_type(memory)
        addr = memory.logical_address
        eip = self.top.getEIP(self.cpu)
        #self.lgr.debug('dataWatch readHap index %d addr 0x%x eip 0x%x' % (index, addr, eip))
        if self.show_cmp:
            self.showCmp(addr)

        if self.break_simulation:
            self.lgr.debug('readHap will break_simulation, set the stop hap')
            self.stopWatch()
            SIM_run_alone(self.setStopHap, None)
        offset = addr - self.start[index]
        cpl = memUtils.getCPL(self.cpu)
        ''' If execution outside of text segment, check for mem-something library call '''
        start, end = self.context_manager.getText()
        call_sp = None
        self.lgr.debug('readHap eip 0x%x start 0x%x  end 0x%x' % (eip, start, end))
        if cpl != 0:
            if not self.break_simulation:
                ''' prevent stack trace from triggering haps '''
                self.stopWatch()
            st = self.top.getStackTraceQuiet(max_frames=3)
            if st is None:
                self.lgr.debug('stack trace is None, wrong pid?')
                return
            #self.lgr.debug('%s' % st.getJson()) 
            ''' look for memcpy'ish... TBD generalize '''
            mem_stuff = st.memsomething()
            #mem_stuff = self.isMemSomething(eip) 
            if mem_stuff is not None:
                self.lgr.debug('DataWatch readHap ret_ip 0x%x' % (mem_stuff.ret_addr))
                ''' src is the referenced memory address by default ''' 
                mem_something = self.MemSomething(mem_stuff.fun, mem_stuff.ret_addr, addr, None, None)
                SIM_run_alone(self.handleMemStuff, mem_something)
            else:
                self.lgr.debug('DataWatch readHap not memsomething, reset the watch')
                self.watch()
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        if op_type == Sim_Trans_Load:
            self.lgr.debug('Data read from 0x%x within input buffer (offset of %d into buffer of %d bytes starting at 0x%x) eip: 0x%x <%s> cycle:0x%x' % (addr, 
                    offset, self.length[index], self.start[index], eip, instruct[1], self.cpu.cycles))
            msg = ('Data read from 0x%x within input buffer (offset of %d into %d bytes starting at 0x%x) eip: 0x%x' % (addr, 
                        offset, self.length[index], self.start[index], eip))
            self.context_manager.setIdaMessage(msg)
            #mark_msg = 'Read from 0x%08x offset %4d into 0x%8x (buf size %4d) %s' % (addr, offset, self.start[index], self.length[index], self.getCmp())
            self.watchMarks.dataRead(addr, self.start[index], self.length[index], self.getCmp())
            if self.break_simulation:
                SIM_break_simulation('DataWatch read data')

            if cpl == 0:
                if not self.break_simulation:
                    self.stopWatch()
                SIM_run_alone(self.kernelReturn, addr)

        elif cpl > 0:
            self.lgr.debug('Data written to 0x%x within input buffer (offset of %d into buffer of %d bytes starting at 0x%x) eip: 0x%x' % (addr, offset, self.length[index], self.start[index], eip))
            self.context_manager.setIdaMessage('Data written to 0x%x within input buffer (offset of %d into %d bytes starting at 0x%x) eip: 0x%x' % (addr, offset, self.length[index], self.start[index], eip))
            if self.break_simulation:
                ''' TBD when to treat buffer as unused?  does it matter?'''
                self.start[index] = 0
                SIM_break_simulation('DataWatch written data')
       
    def showWatch(self):
        for index in range(len(self.start)):
            if self.start[index] != 0:
                print('%d start: 0x%x  length: 0x%x' % (index, self.start[index], self.length[index]))
 
    def setBreakRange(self):
        context = self.context_manager.getRESimContext()
        for index in range(len(self.start)):
            if self.start[index] == 0:
                self.lgr.debug('DataWatch setBreakRange index %d is 0' % index)
                self.read_hap.append(None)
                continue
            break_num = self.context_manager.genBreakpoint(context, Sim_Break_Linear, Sim_Access_Read | Sim_Access_Write, self.start[index], self.length[index], 0)
            end = self.start[index] + self.length[index] 
            eip = self.top.getEIP(self.cpu)
            self.lgr.debug('DataWatch setBreakRange eip: 0x%x Adding breakpoint %d for %x-%x length %x index now %d' % (eip, break_num, self.start[index], end, self.length[index], index))
            self.read_hap.append(self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.readHap, index, break_num, 'dataWatch'))
        if self.back_stop is not None and not self.break_simulation and self.use_back_stop:
            self.back_stop.setFutureCycle(self.back_stop_cycles)

    def stopHap(self, stop_action, one, exception, error_string):
        if stop_action is None or stop_action.hap_clean is None:
            self.lgr.error('dataWatch stopHap error, stop_action None?')
            return
        eip = self.top.getEIP(self.cpu)
        self.lgr.debug('dataWatch stopHap eip 0x%x cycle: 0x%x' % (eip, stop_action.hap_clean.cpu.cycles))

        if self.stop_hap is not None:
            self.lgr.debug('dataWatch stopHap will delete hap %s' % str(self.stop_hap))
            SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.stop_hap)
            self.stop_hap = None
            ''' check functions in list '''
            self.lgr.debug('stopHap now run actions %s' % str(stop_action.flist))
            stop_action.run()
         
    def setStopHap(self, dumb):
        f1 = stopFunction.StopFunction(self.top.skipAndMail, [], nest=False)
        flist = [f1]
        hap_clean = hapCleaner.HapCleaner(self.cpu)
        stop_action = hapCleaner.StopAction(hap_clean, None, flist)
        self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
        	     self.stopHap, stop_action)
        self.lgr.debug('setStopHap set actions %s' % str(stop_action.flist))

    def setShow(self):
        self.show_cmp = ~ self.show_cmp
        return self.show_cmp

    def findRange(self, addr):
        for index in range(len(self.start)):
            if self.start[index] != 0:
                end = self.start[index] + self.length[index]
                self.lgr.debug('findRange is 0x%x between 0x%x and 0x%x?' % (addr, self.start[index], end))
                if addr >= self.start[index] and addr <= end:
                    return self.start[index]
        return None

    def getWatchMarks(self):
        return self.watchMarks.getWatchMarks()

    def goToMark(self, index):
        retval = None
        cycle = self.watchMarks.getCycle(index)
        if cycle is not None:
            SIM_run_command('pselect %s' % self.cpu.name)
            SIM_run_command('skip-to cycle=%d' % cycle)
            retval = cycle
        else:
           self.lgr.error('No data mark with index %d' % index)
        return cycle

    def clearWatchMarks(self): 
        self.watchMarks.clearWatchMarks()

    def clearWatches(self, cycle=None):
        self.lgr.debug('DataWatch clear Watches')
        self.stopWatch()
        self.break_simulation = True
        if cycle is None:
            del self.start[:]
            del self.length[:]
            del self.cycle[:]
        else:
            found = None
            for index in range(len(self.cycle)):
                self.lgr.debug('clearWAtches cycle 0x%x list 0x%x' % (cycle, self.cycle[index]))
                if self.cycle[index] > cycle:
                    self.lgr.debug('clearWatches found cycle index %s' % index)
                    found = index
                    break
            if found is not None:
                self.start = self.start[:index]
                self.length = self.length[:index]
                self.cycle = self.cycle[:index]
                

    def setIdaFuns(self, ida_funs):
        self.ida_funs = ida_funs

    def setRelocatables(self, relocatables):
        self.relocatables = relocatables

    def setCallback(self, callback):
        ''' what should backStop call when no activity for N cycles? '''
        self.back_stop.setCallback(callback)

    def showWatchMarks(self):
        self.watchMarks.showMarks()

    def tagIterator(self, index):
        ''' Call from IDA Client to collapse a range of data references into the given watch mark index ''' 
        if self.ida_funs is not None:
            watch_mark = self.watchMarks.getMarkFromIndex(index)
            if watch_mark is not None:
                fun = self.ida_funs.getFun(watch_mark.ip)
                if fun is None:
                    self.lgr.error('DataWatch tagIterator failed to get function for 0x%x' % ip)
                else:
                    self.user_iterators.add(fun)
                    self.lgr.debug('DataWatch added iterator for function 0x%x' % fun)
            else:
                self.lgr.error('failed to get watch mark for index %d' % index)

    def setUserIterators(self, user_iterators):
        self.user_iterators = user_iterators

    def wouldBreakSimulation(self):
        if self.break_simulation:
            return True
        return False
