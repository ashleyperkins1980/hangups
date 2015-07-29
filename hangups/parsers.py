"""Parser for long-polling responses from the talkgadget API."""

import logging
from collections import namedtuple
import datetime

from hangups import javascript, user, hangouts_pb2, pblite


logger = logging.getLogger(__name__)


def parse_submission(submission):
    """Yield StateUpdate messages from a channel submission."""
    # For each submission payload, yield its messages
    for payload in _get_submission_payloads(submission):
        if payload is not None:
            if isinstance(payload, dict) and 'client_id' in payload:
                # Hack to pass the client ID back to Client
                yield payload
            else:
                yield from _parse_payload(payload)


def _get_submission_payloads(submission):
    """Yield a submission's payloads.

    Most submissions only contain one payload, but if the long-polling
    connection was closed while something happened, there can be multiple
    payloads.
    """
    for sub in javascript.loads(submission):

        if sub[1][0] != 'noop':
            # TODO: can we use json here instead?
            wrapper = javascript.loads(sub[1][0]['p'])
            # pylint: disable=invalid-sequence-index
            if '3' in wrapper and '2' in wrapper['3']:
                client_id = wrapper['3']['2']
                # Hack to pass the client ID back to Client
                yield {'client_id': client_id}
            if '2' in wrapper:
                yield javascript.loads(wrapper['2']['2'])


def _parse_payload(payload):
    """Yield a list of StateUpdate messages."""
    if payload[0] == 'cbu':  # ClientBatchUpdate
        # This is a BatchUpdate containing StateUpdate messages
        batch_update = hangouts_pb2.BatchUpdate()
        # TODO: error handling
        pblite.decode(batch_update, payload, ignore_first_item=True)
        for state_update in batch_update.state_update:
            logger.debug('Received StateUpdate:\n%s', state_update)
            yield state_update
    else:
        logger.info('Ignoring payload with header: {}'.format(payload[0]))


##############################################################################
# Message parsing utils
##############################################################################


def from_timestamp(microsecond_timestamp):
    """Convert a microsecond timestamp to a UTC datetime instance."""
    # Create datetime without losing precision from floating point (yes, this
    # is actually needed):
    return datetime.datetime.fromtimestamp(
        microsecond_timestamp // 1000000, datetime.timezone.utc
    ).replace(microsecond=(microsecond_timestamp % 1000000))


def to_timestamp(datetime_timestamp):
    """Convert UTC datetime to microsecond timestamp used by Hangouts."""
    return int(datetime_timestamp.timestamp() * 1000000)


##############################################################################
# Message types and parsers
##############################################################################


TypingStatusMessage = namedtuple(
    'TypingStatusMessage', ['conv_id', 'user_id', 'timestamp', 'status']
)


def parse_typing_status_message(p):
    """Return TypingStatusMessage from hangouts_pb2.SetTypingNotification.

    The same status may be sent multiple times consecutively, and when a
    message is sent the typing status will not change to stopped.
    """
    return TypingStatusMessage(
        conv_id=p.conversation_id.id,
        user_id=user.UserID(chat_id=p.user_id.chat_id,
                            gaia_id=p.user_id.gaia_id),
        timestamp=from_timestamp(p.timestamp),
        status=p.type,
    )


WatermarkNotification = namedtuple(
    'WatermarkNotification', ['conv_id', 'user_id', 'read_timestamp']
)


def parse_watermark_notification(p):
    """Return WatermarkNotification from hangouts_pb2.WatermarkNotification."""
    return WatermarkNotification(
        conv_id=p.conversation_id.id,
        user_id=user.UserID(
            chat_id=p.participant_id.chat_id,
            gaia_id=p.participant_id.gaia_id,
        ),
        read_timestamp=from_timestamp(
            p.latest_read_timestamp
        ),
    )
