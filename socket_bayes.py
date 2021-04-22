"""
# please install scikit-optimize
# provide HOST, PORT of the server in main functions
1. send message: "start" to start the optmizer
2. it will send back parameters value (format: cc,pp,pipeline,blocksize) for probing, 
    for example: "1,1,4,6" and will wait for throughput value
3. send back throughput values in Mbps, for example: "10000.07"
4. send "-1" to terminate the optimizer
"""
import warnings
warnings.filterwarnings('ignore')

import socket
from skopt.space import Integer
from skopt import Optimizer as BO
import numpy as np
import time
import logging as logger


log_FORMAT = '%(created)f -- %(levelname)s: %(message)s'
logger.basicConfig(format=log_FORMAT, 
                    datefmt='%m/%d/%Y %I:%M:%S %p', 
                    level=logger.INFO)


recv_buffer_size = 8192
  

def harp_response(params):
    global sock
    params = [int(x) for x in params]
    
    n = params[0]
    # format >> "Concurrency"
    output = "{0}".format(params[0])
    
    if len(params) > 1:
        n = params[0] * params[1]
        # format >> "Concurrency,Parallesism,Pipeline,Chunk/Block Size"
        output = "{0},{1},{2},{3}".format(params[0],params[1],params[2],params[3])
        
    logger.info("Sample Transfer -- Probing Parameters: {0}".format(params))
    thrpt = 0
    sock.sendall(output.encode('utf-8'))
    
    while True:
        try:
            message  = sock.recv(recv_buffer_size).decode()
            thrpt = float(message)
            if thrpt is not None:
                break
            
        except Exception as e:
            logger.exception(e)
                
    if thrpt == -1:
        exit(-1)
    else:
        score = (thrpt/(1.02)**n) * (-1)
        logger.info("Sample Transfer -- Throughput: {0}Mbps, Score: {1}".format(
            np.round(thrpt), np.round(score)))
        
    return score


def base_optimizer(black_box_function, mp_opt=False):
    limit_obs, count = 100, 0
    
    if mp_opt:
        search_space  = [
            Integer(1, 32), # Concurrency
            Integer(1, 32), # Parallesism
            Integer(1, 32), # Pipeline
            Integer(0, 20), # Chunk/Block Size: power of 2
            ]
    else:
        search_space  = [
            Integer(1, 32), # Concurrency
            ]
        
    optimizer = BO(
        dimensions=search_space,
        base_estimator="GP", #[GP, RF, ET, GBRT],
        acq_func="gp_hedge", # [LCB, EI, PI, gp_hedge]
        acq_optimizer="auto", #[sampling, lbfgs, auto]
        n_random_starts=8,
        model_queue_size= limit_obs,
    )
        
    while True:
        count += 1

        if len(optimizer.yi) > limit_obs:
            optimizer.yi = optimizer.yi[-limit_obs:]
            optimizer.Xi = optimizer.Xi[-limit_obs:]
            
        logger.info("Iteration {0} Starts ...".format(count))

        t1 = time.time()
        res = optimizer.run(func=black_box_function, n_iter=1)
        t2 = time.time()

        logger.info("Iteration {0} Ends, Took {3} Seconds. Best Params: {1} and Score: {2}.".format(
            count, res.x, np.round(res.fun), np.round(t2-t1, 2)))

        if optimizer.yi[-1] == -1:
            logger.info("Optimizer Exits ...")
            break


if __name__ == '__main__':
    HOST, PORT = "localhost", 32000
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    
    if sock.recv(recv_buffer_size).decode() == "start":
        base_optimizer(harp_response, mp_opt=False)
    
    sock.close()