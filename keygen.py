#!/usr/bin/env python3
"""
keygen.py — License key generator for School Management System.
Run this script to generate license keys for customers.

Usage:
    python keygen.py
    python keygen.py --tier professional --expiry lifetime
    python keygen.py --tier standard --expiry 2026-12-31

KEEP THIS FILE AND YOUR LICENSE_SECRET PRIVATE.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'files'))
import license as _lic

PRICES = {
    'starter':      '$149',
    'standard':     '$299',
    'professional': '$499',
}

def main():
    parser = argparse.ArgumentParser(description='Generate SchoolMS license keys')
    parser.add_argument('--tier', choices=list(_lic.TIERS.keys()),
                        help='License tier (default: interactive prompt)')
    parser.add_argument('--expiry', default=None,
                        help='Expiry date as YYYY-MM-DD, or "lifetime" (default: lifetime)')
    parser.add_argument('--count', type=int, default=1,
                        help='Number of keys to generate (default: 1)')
    args = parser.parse_args()

    tier = args.tier
    expiry = args.expiry or 'lifetime'

    if not tier:
        print('\n  School Management System — License Key Generator')
        print('  ' + '─' * 45)
        print()
        for i, (tid, t) in enumerate(_lic.TIERS.items(), 1):
            users = 'Unlimited' if t['max_users'] >= 9999 else f"Up to {t['max_users']} users"
            print(f'  [{i}] {t["label"]:<16} {users:<22} {PRICES[tid]}')
        print()
        choice = input('  Select tier [1-3]: ').strip()
        tier_list = list(_lic.TIERS.keys())
        try:
            tier = tier_list[int(choice) - 1]
        except (ValueError, IndexError):
            print('Invalid choice.')
            sys.exit(1)

        expiry_in = input('  Expiry [lifetime / YYYY-MM-DD]: ').strip() or 'lifetime'
        expiry = expiry_in

        count_in = input('  How many keys? [1]: ').strip() or '1'
        try:
            args.count = int(count_in)
        except ValueError:
            args.count = 1

    tier_info = _lic.TIERS[tier]
    users = 'Unlimited' if tier_info['max_users'] >= 9999 else f"Up to {tier_info['max_users']} users"

    print()
    print(f'  Tier    : {tier_info["label"]}')
    print(f'  Users   : {users}')
    print(f'  Expiry  : {expiry}')
    print(f'  Keys    : {args.count}')
    print()
    print('  ' + '─' * 60)

    for i in range(args.count):
        key = _lic.generate_key(tier, expiry)
        label = f'  Key {i+1:>3}' if args.count > 1 else '  Key    '
        print(f'{label} : {key}')

    print('  ' + '─' * 60)
    print()
    print('  Give each key to exactly one customer.')
    print('  They paste it into the /activate screen on first run.')
    print()

if __name__ == '__main__':
    main()
