import socket
import os
import numpy as np
import time
import warnings
import datetime
import logging as log
import multiprocessing as mp
from threading import Thread
# from sendfile import sendfile
from config import configurations
from search import  base_optimizer, dummy, brute_force, hill_climb, gradient_ascent

warnings.filterwarnings("ignore", category=FutureWarning)
configurations["cpu_count"] = mp.cpu_count()
configurations["thread_limit"] = configurations['limits']["thread"]
configurations["chunk_limit"] = configurations['limits']["bsize"]
    
if configurations["thread_limit"] == -1:
    configurations["thread_limit"] = configurations["cpu_count"]
    
log_FORMAT = '%(created)f -- %(levelname)s: %(message)s'
log_file = "logs/" + datetime.datetime.now().strftime("%m_%d_%Y_%H_%M_%S") + ".log"
if configurations["loglevel"] == "debug":
    log.basicConfig(format=log_FORMAT, 
                    datefmt='%m/%d/%Y %I:%M:%S %p', 
                    level=log.DEBUG,
                    filename=log_file,
                    filemode="w")
    
    mp.log_to_stderr(log.DEBUG)
else:
    log.basicConfig(format=log_FORMAT, 
                    datefmt='%m/%d/%Y %I:%M:%S %p', 
                    level=log.INFO,
                    filename=log_file,
                    filemode="w")

emulab_test = False
if "emulab_test" in configurations and configurations["emulab_test"] is not None:
    emulab_test = configurations["emulab_test"]

file_transfer = True
if "file_transfer" in configurations and configurations["file_transfer"] is not None:
    file_transfer = configurations["file_transfer"]


manager = mp.Manager()
root = configurations["data_dir"]["sender"]
probing_time = configurations["probing_sec"]
interface = configurations["interface"]
file_names = os.listdir(root) * configurations["multiplier"]
file_sizes = [os.path.getsize(root+filename) for filename in file_names]
file_count = len(file_names)
throughput_logs = manager.list()

chunk_size = (2 ** max(0, configurations["chunk_limit"])) * 1024
num_workers = mp.Value("i", 0)
file_incomplete = mp.Value("i", file_count)
process_status = mp.Array("i", [0 for i in range(configurations["thread_limit"])])
file_offsets = mp.Array("d", [0.0 for i in range(file_count)])

HOST, PORT = configurations["receiver"]["host"], configurations["receiver"]["port"]
RCVR_ADDR = str(HOST) + ":" + str(PORT)


def tcp_stats():
    global interface, RCVR_ADDR
    start = time.time()
    sent, retm = 0, 0
    
    try:
        data = os.popen("ss -ti").read().split("\n")
        for i in range(1,len(data)):
            if RCVR_ADDR in data[i-1]:
                parse_data = data[i].split(" ")
                for entry in parse_data:
                    if "data_segs_out" in entry:
                        sent += int(entry.split(":")[-1])
                        
                    if "retrans" in entry:
                        retm += int(entry.split("/")[-1])
                
    except Exception as e:
        print(e)

    end = time.time()
    log.debug("Time taken to collect tcp stats: {0}ms".format(np.round((end-start)*1000)))
    return sent, retm


def collect_backlog_root_size():
    global RCVR_ADDR
    br_size = 0
    try:
        query = "tc -s qdisc show dev {0} | grep backlog".format(interface)
        br_size = int(os.popen(query).read().split("\n")[0].strip().split(" ")[-1])
                
    except Exception as e:
        print(e)
    
    return br_size


def get_brs_avg(n_time):
    start_time = time.time()
    trans_q = []
    curr_time = time.time()
    prev_value = collect_backlog_root_size()
    
    while (curr_time - start_time) < n_time:
        time.sleep(0.1)
        curr_value = collect_backlog_root_size()
        value = np.abs(curr_value-prev_value)
        trans_q.append(value)
        prev_value = curr_value
        curr_time = time.time()
    
    return int(np.round(np.mean(trans_q[3:])))
        

def worker(process_id, q):
    while file_incomplete.value > 0:
        if process_status[process_id] == 0:
            pass
        else:
            while num_workers.value < 1:
                pass

            log.debug("Start Process :: {0}".format(process_id))
            try:
                sock = socket.socket()
                sock.settimeout(3)
                sock.connect((HOST, PORT))
                
                if emulab_test:
                    target, factor = 20, 10
                    max_speed = (target * 1000 * 1000)/8
                    second_target, second_data_count = int(max_speed/factor), 0

                while (not q.empty()) and (process_status[process_id] == 1):
                    try:
                        file_id = q.get()
                    except:
                        process_status[process_id] = 0
                        break
                    
                    offset = file_offsets[file_id]
                    to_send = file_sizes[file_id] - offset
                    
                    if (to_send > 0) and (process_status[process_id] == 1):
                        filename = root + file_names[file_id]
                        file = open(filename, "rb")
                        msg = file_names[file_id] + "," + str(int(offset)) 
                        msg += "," + str(int(to_send)) + "\n"
                        sock.send(msg.encode())
                            
                        log.debug("starting {0}, {1}, {2}".format(process_id, file_id, filename))
                        timer100ms = time.time()
                       
                        while (to_send > 0) and (process_status[process_id] == 1):
                            if emulab_test:
                                block_size = min(chunk_size, second_target-second_data_count)
                                data_to_send = bytearray(block_size)
                                sent = sock.send(data_to_send)
                            else:
                                block_size = min(chunk_size, to_send)
                                
                                if file_transfer:
                                    sent = sock.sendfile(file=file, offset=int(offset), count=block_size)
                                    # data = os.preadv(file, block_size, offset)
                                else:
                                    data_to_send = bytearray(block_size)
                                    sent = sock.send(data_to_send)
                                
                            offset += sent
                            to_send -= sent
                            file_offsets[file_id] = offset

                            if emulab_test:
                                second_data_count += sent
                                if second_data_count >= second_target:
                                    second_data_count = 0
                                    while timer100ms + (1/factor) > time.time():
                                        pass
                                    
                                    timer100ms = time.time()
                
                    if to_send > 0:
                        q.put(file_id)
                    else:
                        file_incomplete.value = file_incomplete.value - 1
                    
                sock.close()
            
            except socket.timeout as e:
                pass
                
            except Exception as e:
                log.error("Process: {0}, Error: {1}".format(process_id, str(e)))
            
            log.debug("End Process :: {0}".format(process_id))
    
    process_status[process_id] == 0


def get_chunk_size(unit):
    unit = max(unit, 0)
    return (2 ** unit) * 1024


def sample_transfer(params):
    global throughput_logs
    max_cc =  configurations["thread_limit"]
    if file_incomplete.value == 0:
        return 10 ** 10
        
    log.info("Sample Transfer -- Probing Parameters: {0}".format(params))
    num_workers.value = params[0]

    current_cc = np.sum(process_status)
    for i in range(configurations["thread_limit"]):
        if i < params[0]:
            if (i >= current_cc):
                process_status[i] = 1
        else:
            process_status[i] = 0

    log.debug("Active CC: {0}".format(np.sum(process_status)))
    
    time.sleep(1)
    before_sc, before_rc = tcp_stats()
    n_time = probing_time - 1.1
    brs = max(get_brs_avg(n_time), 1)
    # time.sleep(n_time)
    after_sc, after_rc = tcp_stats()
    sc, rc = after_sc - before_sc, after_rc - before_rc
    
    log.info("SC: {0}, RC: {1}, BRS: {2}".format(sc, rc, brs))  
    thrpt = np.mean(throughput_logs[-2:]) if len(throughput_logs) > 2 else 0
        
    lr, C1, C2 = 0, int(configurations["C"]), 0
    if sc != 0:
        lr = rc/sc if sc>rc else 0
    
    brs_rate = np.log2(brs)/100
    factor = C1 * ((1/(1-lr))-1) + C2 * ((1/(1-brs_rate))-1)
    # score_value = thrpt
    score_value = thrpt * (1 - factor)
    cc_factor = (num_workers.value - 1)/max_cc
    score_value = score_value * (1 - cc_factor)
    # score_value = 0.75 * score_value + (0.25 * score_value)/num_workers.value 
    score_value = np.round(score_value * (-1))
    
    log.info("Sample Transfer -- Throughput: {0}Mbps, Loss Rate: {1}%, Score: {2}".format(
        np.round(thrpt), np.round(lr*100, 2), score_value))

    if file_incomplete.value == 0:
        return 10 ** 10
    else:
        return score_value


def normal_transfer(params):
    num_workers.value = params[0]
    log.info("Normal Transfer -- Probing Parameters: {0}".format([num_workers.value]))
    
    for i in range(num_workers.value):
        process_status[i] = 1
    
    while (np.sum(process_status) > 0) and (file_incomplete.value > 0):
        pass

    
def run_transfer():
    if configurations["method"].lower() == "random":
        log.info("Running Random Optimization .... ")
        params = dummy(configurations, sample_transfer, log)
    
    elif configurations["method"].lower() == "brute":
        log.info("Running Brute Force Optimization .... ")
        params = brute_force(configurations, sample_transfer, log)
    
    elif configurations["method"].lower() == "hill_climb":
        log.info("Running Hill Climb Optimization .... ")
        params = hill_climb(configurations, sample_transfer, log)
    
    elif configurations["method"].lower() == "gradient":
        log.info("Running Gradient Optimization .... ")
        params = gradient_ascent(configurations, sample_transfer, log)
    
    elif configurations["method"].lower() == "probe":
        log.info("Running a fixed configurations Probing .... ")
        params = [configurations["probe_config"]["thread"]]
        
    else:
        log.info("Running Bayesian Optimization .... ")
        params = base_optimizer(configurations, sample_transfer, log)
    
    if file_incomplete.value > 0:
        normal_transfer(params)
    

def report_throughput(start_time):
    global throughput_logs
    previous_total = 0
    previous_time = 0

    while file_incomplete.value > 0:
        t1 = time.time()
        time_since_begining = np.round(t1-start_time, 1)
        
        if time_since_begining > 0:
            total_bytes = np.sum(file_offsets)
            thrpt = np.round((total_bytes*8)/(time_since_begining*1000*1000), 2)
            
            curr_total = total_bytes - previous_total
            curr_time_sec = np.round(time_since_begining - previous_time, 3)
            curr_thrpt = np.round((curr_total*8)/(curr_time_sec*1000*1000), 2)
            previous_time, previous_total = time_since_begining, total_bytes
            throughput_logs.append(curr_thrpt)
            log.info("Throughput @{0}s: Current: {1}Mbps, Average: {2}Mbps".format(
                time_since_begining, curr_thrpt, thrpt))
            t2 = time.time()
            time.sleep(max(0, 1 - (t2-t1)))


if __name__ == '__main__':
    q = manager.Queue(maxsize=file_count)
    for i in range(file_count):
        q.put(i)
        
    workers = [mp.Process(target=worker, args=(i, q)) for i in range(configurations["thread_limit"])]
    for p in workers:
        p.daemon = True
        p.start()
    
    start = time.time()
    reporting_process = mp.Process(target=report_throughput, args=(start,))
    reporting_process.daemon = True
    reporting_process.start()
    run_transfer()
    end = time.time()
            
    time_since_begining = np.round(end-start, 3)
    total = np.round(np.sum(file_offsets) / (1024*1024*1024), 3)
    thrpt = np.round((total*8*1024)/time_since_begining,2)
    log.info("Total: {0} GB, Time: {1} sec, Throughput: {2} Mbps".format(
        total, time_since_begining, thrpt))
    
    reporting_process.terminate()
    for p in workers:
        if p.is_alive():
            p.terminate()
            p.join(timeout=0.1)
