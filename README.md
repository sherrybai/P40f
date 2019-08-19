# P40f

To run in Mininet on the [P4 tutorials VM](https://github.com/p4lang/tutorials/tree/dc08948a344c6ff26af47d2a2447800cab94ab49):

1. Change directory to `./src`, then run `make`.
2. In another terminal window, run the controller: `python controller.py`. This installs fingerprinting rules onto the switch.
3. To replay a packet capture through the switch, open h1's terminal by running `xterm h1` in Mininet, then run `tcpreplay -x 0.1 -i "h1-eth0" [PCAP FILENAME].pcap` in h1's terminal. The replay speed 0.1 can be adjusted if necessary.
4. We can produce a text file `p4_result.txt` containing an OS label for each TCP SYN packet in the capture as follows:
    - Run `grep "Action entry is MyIngress.set_result" logs/s1.log > grep_result.txt`.
    - Run `python p4_result.py > p4_result.txt`. 
