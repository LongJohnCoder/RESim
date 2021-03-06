import idaapi
import idc
import idaversion
def getOffset():
    '''
    Assuming an offset, e.g., "var_11" is highlighted, and
    assuming bp is proper, get the calculated address.
    '''
    retval = None
    ip = idaversion.get_screen_ea()
    
    print('ip is 0x%x' % ip)
    highlighted = idaversion.getHighlight()
    print('highlighted is %s' % highlighted)
    
    ov0 = idc.print_operand(ip, 0)
    ov1 = idc.print_operand(ip, 1)
    print('op0 %s  op1 %s' % (ov0, ov1))
    
    if highlighted in ov0:
        index = 0
        want = ov0
    else:
        index = 1
        want = ov1
    ''' Convert to numberic from symbol '''
    idc.op_seg(ip, index)
    if '[' in want and '+' in want or '-' in want:
        op = idc.print_operand(ip, index)
        print('op is %s' % op)
        val = op.split('[', 1)[1].split(']')[0]
        print('val %s' % val)
        if '+' in val:
            reg,value = val.split('+')
        else:
            reg,value = val.split('-')
        reg_val = idaversion.get_reg_value(reg)
        try:
            value = value.strip('h')
            value = int(value, 16)
        except:
            print('unable to parse int from %s' % value)
            idc.op_stkvar(ip, 0)
            return retval
        
        if '+' in val:
            retval = reg_val + value
        else:
            retval = reg_val - value
        print('effective addr is 0x%x' % retval)
    
    ''' Convert back to symbol, e.g., var_11'''
    idc.op_stkvar(ip, index)
    return retval

def isHighlightedEffective():
    ip = idaversion.get_screen_ea()
    instr = idc.GetDisasm(ip)
    if '[' in instr:
        val = instr.split('[', 1)[1].split(']')[0]
        highlighted = idaversion.getHighlight()
        if highlighted in val:
            return True
        else:
            return False
        
    
