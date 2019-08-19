import sys
from pprint import pprint
from fp_compiler import P0fDatabaseReader

reader = P0fDatabaseReader()

p4 = []
with open("grep_result.txt") as f:
    for line in f:
        field_list = line.split()
        label_id = field_list[-1]
        if "miss" in label_id:
            p4.append("???")
        else:
            label_id = label_id.split(',')[0]
            label = reader.id_to_label(int(label_id, 16))
            if "???" in label:
                p4.append("???")
            else:
                name = label.split(':')
                p4.append(' '.join(name[2:]).strip())

pprint(p4)
