import sys
import time
import select
import os

from optparse import OptionParser

# global variables and methods
VERSION = '0.1'

# class definitions
class NetemAdjustor:
    def __init__(self, dst_dev):
        self.dst_dev = dst_dev

        self.haveRoot = False
        self.nClass = 0

    def reset(self):
        self.logger.info('RESET')
        comm = 'tc qdisc del dev %s root handle 1:' % self.dst_dev

        print('comm: %s' % comm)

        ret = os.system(comm)

        if ret is not 0:
            print('RESET FAIL')
            print('failed comm: %s' % comm)

            self.haveRoot = False
            self.nClass = 0
            return
        else:
            print('RESET SUCCESS')

        self.haveRoot = False
        self.nClass = 0

    def _getClassId(self):
        if self.haveRoot:
            self.nClass += 1
            return '1:%d' % self.nClass
        else:
            self.nClass = 1
            return '1:1'

    def adjust(self, host, delay_ms, bandwidth_mbit, loss_rate_str, unparsed_except_list):
        print('ADJUSTING: %s(delay: %dms / bandwidth: %dMbit / loss_rate: %s%%)' % (host, delay_ms, bandwidth_mbit, loss_rate_str))

        # parsing exception list
        except_list = []
        max_bw = bandwidth_mbit

        for unparsed_ex in unparsed_except_list:
            print('except: %s' % unparsed_ex)

            tokens = unparsed_ex.split('|')

            ex = {}

            try:
                ex['addr'] = tokens[0]
            except:
                print('failed to parse to exception token: %s' % unparsed_ex)
                continue

            try:
                ex['delay'] = int(tokens[1])
            except:
                ex['delay'] = 0

            try:
                ex['bw'] = int(tokens[2])
            except:
                ex['bw'] = 1000

            if ex['bw'] == 0:
                ex['bw'] == 1000

            if ex['bw'] > max_bw:
                max_bw = ex['bw']

            try:
                ex['loss_str'] = tokens[3]
            except:
                ex['loss_str'] = ''

            except_list.append(ex)

        # adding root
        if not self.haveRoot:
            class_id = self._getClassId()

            r2q_val = float(max_bw * 1024 * 1024) / 8 / 1500 * 1.1
            r2q_val = int(r2q_val)

            comm0 = 'tc qdisc add dev %s handle 1: root htb r2q %d' % (self.dst_dev, r2q_val)
            print('comm: %s' % comm0)

            ret = os.system(comm0)

            if ret is not 0:
                print('ADJUSTING FAIL: adding tc root')
                print('failed comm: %s' % comm0)
                return
            else:
                self.haveRoot = True

            # adding cdn filter which doesn't need delay
            for ex in except_list:
                class_id = self._getClassId()

                comm = 'tc class add dev %s parent 1: classid %s htb rate %dMbit' % (self.dst_dev, class_id, ex['bw'])
                print('comm: %s' % comm)

                ret = os.system(comm)

                if ret is not 0:
                    print('ADJUSTING FAIL: adding tc class for exception')
                    print('failed comm: %s' % comm)
                    return

                comm = 'tc filter add dev %s parent 1: protocol ip prio 1 u32 match ip src %s flowid %s' % (self.dst_dev, ex['addr'], class_id)
                print('comm: %s' % comm)

                ret = os.system(comm)

                if ret is not 0:
                    print('ADJUSTING FAIL: adding tc src filter for exception')
                    print('failed comm: %s' % comm)
                    continue

                comm = 'tc filter add dev %s parent 1: protocol ip prio 1 u32 match ip dst %s flowid %s' % (self.dst_dev, ex['addr'], class_id)
                print('comm: %s' % comm)

                ret = os.system(comm)

                if ret is not 0:
                    print('ADJUSTING FAIL: adding tc src filter for exception')
                    print('failed comm: %s' % comm)
                    continue

        # adding class
        class_id = self._getClassId()

        if bandwidth_mbit == 0:
            comm1 = 'tc class add dev %s parent 1: classid %s htb rate 1000Mbit' % (self.dst_dev, class_id)
        else:
            comm1 = 'tc class add dev %s parent 1: classid %s htb rate %dMbit ceil %dMbit' % (self.dst_dev, class_id, bandwidth_mbit, bandwidth_mbit)

        print('comm: %s' % comm1)
        ret = os.system(comm1)

        if ret is not 0:
            print('ADJUSTING FAIL: adding tc class')
            print('failed comm: %s' % comm1)
            return

        # adding filter
        comm2 = 'tc filter add dev %s parent 1: protocol ip prio 1 u32 match ip src %s/32 flowid %s' % (self.dst_dev, host, class_id)

        print('comm: %s' % comm2)
        ret = os.system(comm2)

        if ret is not 0:
            print('ADJUSTING FAIL: adding tc filter to %s(src)' % host)
            print('failed comm: %s' % comm2)
            return

        comm3 = 'tc filter add dev %s parent 1: protocol ip prio 1 u32 match ip dst %s/32 flowid %s' % (self.dst_dev, host, class_id)

        print('comm: %s' % comm3)
        ret = os.system(comm3)

        if ret is not 0:
            print('ADJUSTING FAIL: adding tc filter to %s(dst)' % host)
            print('failed comm: %s' % comm3)
            return

        # adding netem
        netem_opt = ''

        if delay_ms is not 0:
            netem_opt += 'delay %dms' % delay_ms

        if loss_rate_str is not '' and loss_rate_str is not '0':
            netem_opt += ' loss %s%%' % loss_rate_str

        if netem_opt != '':
            comm4 = 'tc qdisc add dev eth1 parent %s handle %d netem %s' % (class_id, self.nClass + 10, netem_opt)

            print('comm: %s' % comm4)

            ret = os.system(comm4)

            if ret is not 0:
                print('ADJUSTING FAIL: adding tc netem')
                print('failed comm: %s' % comm4)
                return

        print('ADJUSTING SUCCESS: %s(delay: %dms / bandwidth: %dMbit / loss_rate: %s%%)' % (host, delay_ms, bandwidth_mbit, loss_rate_str))


def main():
    parser = OptionParser(usage="usage: %prog [options]", version="%prog 0.1")
    parser.add_option("-r", "--reset", action="store_true", dest="reset_flag", default=False,
                      help="Reset to original states")
    parser.add_option("-i", "--interface", action="store", dest="host", default="eth0",
                      help="Interface name")
    parser.add_option("-d", "--delay", action="store", dest="delay_ms", default="0",
                      help="Delay(ms)")
    parser.add_option("-b", "--bandwidth", action="store", dest="bandwidth_mbit", default="0",
                      help="Bandwidth(MBit)")
    parser.add_option("-e", "--excepts", action="store", dest="except_list", default="",
                      help="Exception list")

    (options, args) = parser.parse_args()

    print options
    print args

	adjustor = NetemAdjustor(device)
    adjustor.reset()

    if options['reset_flag'] is True:
        sys.exit(0)

    new_except_list = []
    if except_list is not '':
        tokens = except_list.split(',')

        for tok in tokens:
            new_except_list.append(tok)

    host = options['host']
    delay_ms = int(options['delay_ms'])
    bandwidth_mbit = int(options['bandwidth_mbit'])
    loss_rate_str = ''

    adjustor.adjust(host, delay_ms, bandwidth_mbit, loss_rate_str, new_except_list)
    print("FINISHED")

if __name__ == '__main__':
	main()
