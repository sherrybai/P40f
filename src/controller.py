#!/usr/bin/env python2
import argparse
import grpc
import os
import sys
from fp_compiler import P0fDatabaseReader
from time import sleep
from pprint import pprint

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../utils/'))
import p4runtime_lib.bmv2
from p4runtime_lib.switch import ShutdownAllSwitchConnections
import p4runtime_lib.helper


def writeIpv4ForwardingRules(p4info_helper,
                             ingress_sw,
                             egress_sw,
                             ingress_port,
                             egress_port,
                             dst_eth_addr,
                             dst_ip_addr):
    """
    :param p4info_helper: the P4Info helper
    :param ingress_sw: the ingress switch connection
    :param egress_sw: the egress switch connection
    :param ingress_port: the port on which ingress_sw forwards
    :param egress_port: the port on which egress_sw forwards
    :param dst_eth_addr: the destination Ethernet address to write
    :param dst_ip_addr: the destination IP to match
    """

    # (1) Ingress rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": ingress_port
        })
    ingress_sw.WriteTableEntry(table_entry)
    print "Installed ingress IPv4 forwarding rule on %s" % ingress_sw.name

    # (2) Egress rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": egress_port
        })
    egress_sw.WriteTableEntry(table_entry)
    print "Installed egress IPv4 forwarding rule on %s" % egress_sw.name


def writeP0fRules(p4info_helper, sw):
    # Read signature list
    reader = P0fDatabaseReader()
    sig_list = reader.get_signature_list()

    # Iterate over all signatures in order
    # Signatures appearing earlier are assigned higher priorities
    for sig in sig_list:
        # Create table entry
        # All fields in sig object belong to the p0f_metadata struct
        match_field_prefix = 'meta.p0f_metadata.'
        table_name = 'MyIngress.result_match'
        is_generic_fuzzy = 1 if (sig.is_generic or sig.is_fuzzy) else 0
        action_params = {
                "result": sig.label_id,
                "is_generic_fuzzy": is_generic_fuzzy
            }
        for param in sig.extra_params:
            action_params[param] = sig.extra_params[param]
        
        table_entry = p4info_helper.buildTableEntry(
            table_name=table_name,
            match_fields=sig.get_match_fields_dict(),
            action_name=sig.action,
            action_params=action_params,
            priority=sig.priority
        )

        # Write table entry
        sw.WriteTableEntry(table_entry)
        print("Installed {} {} p0f rule for {} (id {}) on {}" \
              .format("generic" if sig.is_generic else "specific",
                      "fuzzy" if sig.is_fuzzy else "non-fuzzy",
                      sig.label,
                      sig.label_id,
                      sw.name))

    print("Installed all p0f rules on {}".format(sw.name))

def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print '\n----- Reading tables rules for %s -----' % sw.name
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            
            # Print table name instead of table id
            table_name = p4info_helper.get_tables_name(entry.table_id)
            print "table_name: %s" % table_name

            # Print match
            match_string = "match {\n"
            for m in entry.match:
                field_name = p4info_helper.get_match_field_name(table_name, m.field_id)
                match_string += "  field_name: %s\n" % field_name
                match_string += "  %s {\n" % m.WhichOneof("field_match_type")
                match_string += "    value: %r\n" % (p4info_helper.get_match_field_value(m),)
                match_string += "  }\n"
            match_string += "}"
            print match_string

            # Print action
            action_string = "action {\n"
            action_string += "  action {\n"
            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)
            action_string += "    action_name: %s\n" % action_name
            for p in action.params:
                action_string += "    params {\n"
                action_string += "      param_name: %s\n" % p4info_helper.get_action_param_name(action_name, p.param_id)
                action_string += "      value: %r\n" % p.value
                action_string += "    }\n"
            action_string += "  }\n"
            action_string += "}"
            print action_string
            
            print '-----'

        
def printGrpcError(e):
    print "gRPC Error:", e.details(),
    status_code = e.code()
    print "(%s)" % status_code.name,
    traceback = sys.exc_info()[2]
    print "[%s:%d]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno)

    
def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1 and s3;
        # this is backed by a P4Runtime gRPC connection.
        # Also, dump all P4Runtime messages sent to switch to given txt files.
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')
        s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s3',
            address='127.0.0.1:50052',
            device_id=1,
            proto_dump_file='logs/s3-p4runtime-requests.txt')

        # Send master arbitration update message to establish this controller as
        # master (required by P4Runtime before performing any other write operation)
        s1.MasterArbitrationUpdate()
        s3.MasterArbitrationUpdate()

        # Install the P4 program on the switches
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForwardingPipelineConfig on s1"
        s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForwardingPipelineConfig on s3"

        # Write the rules that forward traffic from h1 to h3
        writeIpv4ForwardingRules(p4info_helper,
                                 ingress_sw=s1,
                                 egress_sw=s3,
                                 ingress_port=3,
                                 egress_port=1,
                                 dst_eth_addr="00:00:00:00:03:03",
                                 dst_ip_addr="10.0.3.3")

        # Write the rules that forward traffic from h3 to h1
        writeIpv4ForwardingRules(p4info_helper,
                                 ingress_sw=s3,
                                 egress_sw=s1,
                                 ingress_port=2,
                                 egress_port=1,
                                 dst_eth_addr="00:00:00:00:01:01",
                                 dst_ip_addr="10.0.1.1")

        # Write p0f rules to s1
        writeP0fRules(p4info_helper, s1)

        # Read and print table rules for s1 and s3
        # readTableRules(p4info_helper, s1)
        # readTableRules(p4info_helper, s3)

    except KeyboardInterrupt:
        print " Shutting down."
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/p40f.p4info')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/p40f.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print "\np4info file not found: %s\nHave you run 'make'?" % args.p4info
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print "\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json
        parser.exit(1)
    main(args.p4info, args.bmv2_json)
