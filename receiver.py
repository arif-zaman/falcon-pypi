import socket
import multiprocessing as mp
import logging
import time
from config import configurations

HOST, PORT = configurations["receiver"]["host"], configurations["receiver"]["port"]
if configurations["loglevel"] == "debug":
    logger = mp.log_to_stderr(logging.DEBUG)
else:
    logger = mp.log_to_stderr(logging.INFO)
    

def worker(socket):
    while True:
        client, address = socket.accept()
        logger.debug("{u} connected".format(u=address))
        
        chunk = client.recv(BUFFER_SIZE)
        while chunk:
            chunk = client.recv(BUFFER_SIZE)


if __name__ == '__main__':
    num_workers = mp.cpu_count()
    sock = socket.socket()
    sock.bind((HOST, PORT))
    sock.listen(num_workers)
    
    BUFFER_SIZE = 256 * 1024 * 1024
    total = 0

    workers = [mp.Process(target=worker, args=(sock,)) for i in range(num_workers)]
    for p in workers:
        p.daemon = True
        p.start()

    while True:
        try:
            time.sleep(10)
        except:
            break