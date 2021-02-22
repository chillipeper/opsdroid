"""A connector for Slack."""
import json
import logging
import os
import re
import ssl

import aiohttp
import certifi
from emoji import demojize
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from voluptuous import Required

import opsdroid.events
from opsdroid.connector import Connector, register_event
from opsdroid.connector.slack.create_events import SlackEventCreator
from opsdroid.connector.slack.events import Blocks, EditedBlocks


_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = {
    Required("token"): str,
    "user-token": str,
    "bot-name": str,
    "default-room": str,
    "icon-emoji": str,
    "start_thread": bool,
}


class ConnectorSlack(Connector):
    """A connector for Slack."""

    def __init__(self, config, opsdroid=None):
        """Create the connector."""
        super().__init__(config, opsdroid=opsdroid)
        _LOGGER.debug(_("Starting Slack connector."))
        self.name = "slack"
        self.default_target = config.get("default-room", "#general")
        self.icon_emoji = config.get("icon-emoji", ":robot_face:")
        self.token = config["token"]
        self.start_thread = config.get("start_thread", False)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.slack_web_client = AsyncWebClient(
            token=self.token, ssl=self.ssl_context, proxy=os.environ.get("HTTPS_PROXY"),
        )
        self.bot_name = config.get("bot-name", "opsdroid")
        self.auth_info = None
        self.user_info = None
        self.bot_id = None
        self.known_users = {}

        self._event_creator = SlackEventCreator(self)

    async def connect(self):
        """Connect to the chat service."""
        _LOGGER.info(_("Connecting to Slack."))

        try:
            self.auth_info = (await self.slack_web_client.api_call("auth.test")).data
            self.user_info = (
                await self.slack_web_client.api_call(
                    "users.info",
                    http_verb="GET",
                    params={"user": self.auth_info["user_id"]},
                )
            ).data
            self.bot_id = self.user_info["user"]["profile"]["bot_id"]

            self.opsdroid.web_server.web_app.router.add_post(
                "/connector/{}".format(self.name), self.slack_event_handler,
            )

            _LOGGER.debug(_("Connected as %s."), self.bot_name)
            _LOGGER.debug(_("Using icon %s."), self.icon_emoji)
            _LOGGER.debug(_("Default room is %s."), self.default_target)
            _LOGGER.info(_("Connected successfully."))
        except SlackApiError as error:
            _LOGGER.error(
                _(
                    "Unable to connect to Slack due to %s."
                    "The Slack Connector will not be available."
                ),
                error,
            )

    async def disconnect(self):
        """Disconnect from Slack."""

    async def listen(self):
        """Listen for and parse new messages."""

    async def slack_event_handler(self, request):
        """Handle events from the Events API and Interactive actions in Slack.

        Following types are handled:
            url_verification, event_callback, block_actions, message_action, view_submission, view_closed

        Return:
            A 200 OK response. The Messenger Platform will resend the webhook
            event every 20 seconds, until a 200 OK response is received.
            Failing to return a 200 OK may cause your webhook to be
            unsubscribed by the Messenger Platform.

        """

        event = None
        payload = {}

        if request.content_type == "application/x-www-form-urlencoded":
            req = await request.post()
            payload = json.loads(req["payload"])
        elif request.content_type == "application/json":
            payload = await request.json()

        if "type" in payload:
            if payload["type"] == "url_verification":
                return aiohttp.web.json_response({"challenge": payload["challenge"]})

            elif payload["type"] == "event_callback":
                event = await self._event_creator.create_event(payload["event"], None)
            elif payload["type"] in (
                "block_actions",
                "message_action",
                "view_submission",
                "view_closed",
            ):
                event = await self._event_creator.create_event(payload, None)
            else:
                _LOGGER.info(
                    f"Payload: {payload['type']} is not implemented. Event wont be parsed"
                )

        if isinstance(event, list):
            for e in event:
                _LOGGER.debug(f"Got slack event: {e}")
                await self.opsdroid.parse(event)

        if isinstance(event, opsdroid.events.Event):
            _LOGGER.debug(f"Got slack event: {event}")
            await self.opsdroid.parse(event)

        return aiohttp.web.Response(text=json.dumps("Received"), status=200)

    async def lookup_username(self, userid):
        """Lookup a username and cache it."""

        if userid in self.known_users:
            user_info = self.known_users[userid]
        else:
            response = await self.slack_web_client.users_info(user=userid)
            user_info = response.data["user"]

            if isinstance(user_info, dict):
                self.known_users[userid] = user_info

        return user_info

    async def replace_usernames(self, message):
        """Replace User ID with username in message text."""
        userids = re.findall(r"\<\@([A-Z0-9]+)(?:\|.+)?\>", message)

        for userid in userids:
            user_info = await self.lookup_username(userid)
            message = message.replace(
                "<@{userid}>".format(userid=userid), user_info["name"]
            )

        return message

    @register_event(opsdroid.events.Message)
    async def _send_message(self, message):
        """Respond with a message."""
        _LOGGER.debug(
            _("Responding with: '%s' in room  %s."), message.text, message.target
        )
        data = {
            "channel": message.target,
            "text": message.text,
            "username": self.bot_name,
            "icon_emoji": self.icon_emoji,
        }

        if message.linked_event:
            if "thread_ts" in message.linked_event.raw_event:
                if (
                    message.linked_event.event_id
                    != message.linked_event.raw_event["thread_ts"]
                ):
                    # Linked Event is inside a thread
                    data["thread_ts"] = message.linked_event.raw_event["thread_ts"]
            elif self.start_thread:
                data["thread_ts"] = message.linked_event.event_id

        return await self.slack_web_client.api_call("chat.postMessage", data=data,)

    @register_event(opsdroid.events.EditedMessage)
    async def _edit_message(self, message):
        """Edit a message."""
        _LOGGER.debug(
            _("Editing message with timestamp: '%s' to %s in room  %s."),
            message.linked_event,
            message.text,
            message.target,
        )
        data = {
            "channel": message.target,
            "ts": message.linked_event,
            "text": message.text,
        }

        return await self.slack_web_client.api_call("chat.update", data=data,)

    @register_event(Blocks)
    async def _send_blocks(self, blocks):
        """Respond with structured blocks."""
        _LOGGER.debug(
            _("Responding with interactive blocks in room %s."), blocks.target
        )

        return await self.slack_web_client.api_call(
            "chat.postMessage",
            data={
                "channel": blocks.target,
                "username": self.bot_name,
                "blocks": blocks.blocks,
                "icon_emoji": self.icon_emoji,
            },
        )

    @register_event(EditedBlocks)
    async def _edit_blocks(self, blocks):
        """Edit a particular block."""
        _LOGGER.debug(
            _("Editing interactive blocks with timestamp: '%s' in room  %s."),
            blocks.linked_event,
            blocks.target,
        )
        data = {
            "channel": blocks.target,
            "ts": blocks.linked_event,
            "blocks": blocks.blocks,
        }

        return await self.slack_web_client.api_call("chat.update", data=data,)

    @register_event(opsdroid.events.Reaction)
    async def send_reaction(self, reaction):
        """React to a message."""
        emoji = demojize(reaction.emoji).replace(":", "")
        _LOGGER.debug(_("Reacting with: %s."), emoji)
        try:
            return await self.slack_web_client.api_call(
                "reactions.add",
                data={
                    "name": emoji,
                    "channel": reaction.target,
                    "timestamp": reaction.linked_event.event_id,
                },
            )
        except SlackApiError as error:
            if "invalid_name" in str(error):
                _LOGGER.warning(_("Slack does not support the emoji %s."), emoji)
            else:
                raise

    @register_event(opsdroid.events.NewRoom)
    async def _send_room_creation(self, creation_event):
        _LOGGER.debug(_("Creating room %s."), creation_event.name)

        return await self.slack_web_client.api_call(
            "conversations.create", data={"name": creation_event.name}
        )

    @register_event(opsdroid.events.RoomName)
    async def _send_room_name_set(self, name_event):
        _LOGGER.debug(
            _("Renaming room %s to '%s'."), name_event.target, name_event.name
        )

        return await self.slack_web_client.api_call(
            "conversations.rename",
            data={"channel": name_event.target, "name": name_event.name},
        )

    @register_event(opsdroid.events.JoinRoom)
    async def _send_join_room(self, join_event):
        return await self.slack_web_client.api_call(
            "conversations.join", data={"channel": join_event.target}
        )

    @register_event(opsdroid.events.UserInvite)
    async def _send_user_invitation(self, invite_event):
        _LOGGER.debug(
            _("Inviting user %s to room '%s'."), invite_event.user, invite_event.target
        )

        return await self.slack_web_client.api_call(
            "conversations.invite",
            data={"channel": invite_event.target, "users": invite_event.user_id},
        )

    @register_event(opsdroid.events.RoomDescription)
    async def _send_room_description(self, desc_event):
        return await self.slack_web_client.api_call(
            "conversations.setTopic",
            data={"channel": desc_event.target, "topic": desc_event.description},
        )

    @register_event(opsdroid.events.PinMessage)
    async def _send_pin_message(self, pin_event):
        return await self.slack_web_client.api_call(
            "pins.add",
            data={
                "channel": pin_event.target,
                "timestamp": pin_event.linked_event.event_id,
            },
        )

    @register_event(opsdroid.events.UnpinMessage)
    async def _send_unpin_message(self, unpin_event):
        return await self.slack_web_client.api_call(
            "pins.remove",
            data={
                "channel": unpin_event.target,
                "timestamp": unpin_event.linked_event.event_id,
            },
        )