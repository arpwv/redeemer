#! /usr/bin/env python3
# coding=utf-8
import traceback
import time
import configargparse
import os
import json
import logging
import sys
import signal

from redeemer import Delegator, Stats, Notifier, get_deplorables

parser = configargparse.ArgumentParser(
    'redeemer', formatter_class=configargparse.ArgumentDefaultsRawHelpFormatter)
parser.add_argument(
    '--sendgrid_api_key',
    default=None,
    type=str,
    help='api key to use Sendgrid to send notification messages',
    env_var="SENDGRID_API_KEY")
parser.add_argument(
    '--send_messages_to',
    default=None,
    type=str,
    help='comma-separated list of email addresses to send messages to',
    env_var="SEND_MESSAGES_TO")
parser.add_argument(
    '--notification_interval',
    default=86400,
    type=int,
    help='time in seconds between status emails',
    env_var="NOTIFICATION_INTERVAL")
parser.add_argument(
    '--account',
    type=str,
    help='Account to perform delegations for',
    env_var="ACCOUNT")
parser.add_argument(
    '--wif',
    type=configargparse.FileType('r'),
    help='An active WIF for account. The flag expects a path to a file. The environment variable REDEEMER_WIF will be checked for a literal WIF also.')
parser.add_argument(
    '--log_level',
    type=str,
    default='INFO',
    env_var="LOG_LEVEL")
parser.add_argument(
    '--dry_run',
    type=int,
    default=1,
    help='Set this to 0 to actually broadcast transactions',
    env_var="DRY_RUN")
parser.add_argument(
    '--interval',
    type=int,
    default=60 * 60 * 2,
    help='Time in seconds to wait between polling for new delegations',
    env_var="INTERVAL")
parser.add_argument(
    '--deplorables_url',
    default=None,
    type=str,
    help='url to retrieve list of deplorables from',
    env_var="DEPLORABLES_URL")

args = parser.parse_args()

logger = logging.getLogger("redeemer")
logging.basicConfig(level=logging.getLevelName(args.log_level))

wifs = []
if args.wif:
    logger.info('Using wif from file %s' % args.wif)
    wifs = args.wif.read().strip().split(':')
elif os.environ.get('REDEEMER_WIF') is not None:
    logger.info('Using wif from environment variable REDEEMER_WIF')
    wifs = os.environ.get('REDEEMER_WIF').strip().split(':')
else:
    logger.warn(
        'You have not specified a wif; signing transactions is not possible!')

if args.sendgrid_api_key and args.send_messages_to:
    logger.info(
        'Using sendgrid to send notification emails to %s',
        args.send_messages_to)
elif not args.send_messages_to:
    logger.warn('No send_messages_to address supplied, no messages will be sent')
else:
    logger.warn('No sendgrid key supplied, no messages will be sent')

if args.dry_run == 1:
    logger.warn("dry run mode; no transactions will be broadcast")

logger.info("pid %d. send USR1 to get stats so far", os.getpid())


def log_stats(*args):
    if in_run:
        logger.info("at index %s" % last_idx)
        logger.info(stats.get())
    else:
        logger.info("Not running right now.")


signal.signal(signal.SIGUSR1, log_stats)

send_messages_to = []
if args.send_messages_to is not None and args.send_messages_to != "":
    send_messages_to = args.send_messages_to.split(",")
notifier = Notifier(args.sendgrid_api_key, send_messages_to)
stats = Stats()

last_email_time = 0
last_idx = ""
in_run = False

while True:
    in_run = True

    try:
        deplorables = get_deplorables(args.deplorables_url)
        logger.info("%d deplorables loaded", len(deplorables))
        delegator = Delegator(logger=logger, deplorables=deplorables)
        last_idx = ""
        while last_idx is not None:
            deltas, last_idx = delegator.delegate(
                args.account, last_idx=last_idx, dry_run=(
                    args.dry_run == 1), wifs=wifs)
            for delta in deltas:
                stats.add(delta['name'], delta['delta_vests'])
        log_stats()
        if time.time() - last_email_time > args.notification_interval:
            logger.info("sending status email")
            notifier.notify_stats(stats.get())
            last_email_time = time.time()
            stats.reset()

    except Exception as e:
        logger.exception("RUN FAILED")
        notifier.notify_error(traceback.format_exc())

    in_run = False
    
    logger.info("Waiting %d seconds until the next run", args.interval)
    time.sleep(args.interval)
