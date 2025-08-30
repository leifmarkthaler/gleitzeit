#!/usr/bin/env python3
"""
CPU-intensive script for testing resource limits
"""

import json
import sys
import math
import time

def calculate_primes(n):
    """Calculate first n prime numbers"""
    primes = []
    num = 2
    
    while len(primes) < n:
        is_prime = True
        for i in range(2, int(math.sqrt(num)) + 1):
            if num % i == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(num)
        num += 1
    
    return primes

def main():
    """Main function"""
    n = 100  # Default
    
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except ValueError:
            pass
    
    start_time = time.time()
    primes = calculate_primes(n)
    elapsed = time.time() - start_time
    
    result = {
        "task": f"Calculate first {n} prime numbers",
        "count": len(primes),
        "first_10": primes[:10],
        "last": primes[-1] if primes else None,
        "elapsed_seconds": round(elapsed, 3)
    }
    
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())