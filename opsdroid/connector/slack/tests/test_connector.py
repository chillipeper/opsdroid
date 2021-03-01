"""Tests for the ConnectorSlack class."""
import json

import pytest
from opsdroid import events
from opsdroid.connector.slack.connector import SlackApiError
from opsdroid.connector.slack.events import Blocks, EditedBlocks

from .conftest import get_path

USERS_INFO = ("/users.info", "GET", get_path("method_users.info.json"), 200)
AUTH_TEST = ("/auth.test", "POST", get_path("method_auth.test.json"), 200)
CHAT_POST_MESSAGE = ("/chat.postMessage", "POST", {"ok": True}, 200)
CHAT_UPDATE_MESSAGE = ("/chat.update", "POST", {"ok": True}, 200)
REACTIONS_ADD = ("/reactions.add", "POST", {"ok": True}, 200)
CONVERSATIONS_CREATE = ("/conversations.create", "POST", {"ok": True}, 200)
CONVERSATIONS_RENAME = ("/conversations.rename", "POST", {"ok": True}, 200)
CONVERSATIONS_JOIN = ("/conversations.join", "POST", {"ok": True}, 200)
CONVERSATIONS_INVITE = ("/conversations.invite", "POST", {"ok": True}, 200)
CONVERSATIONS_SET_TOPIC = ("/conversations.setTopic", "POST", {"ok": True}, 200)
PINS_ADD = ("/pins.add", "POST", {"ok": True}, 200)
PINS_REMOVE = ("/pins.remove", "POST", {"ok": True}, 200)


@pytest.fixture
async def send_event(connector, mock_api):
    """Mock a send opsdroid event and return payload used and response from the request"""

    async def _send_event(api_call, event):
        api_endpoint, *_ = api_call
        response = await connector.send(event)
        payload = mock_api.get_payload(api_endpoint)

        return payload, response

    return _send_event


@pytest.mark.asyncio
class TestConnectorSlack:
    """Test the opsdroid Slack connector class."""

    @pytest.mark.add_response(*USERS_INFO)
    @pytest.mark.add_response(*AUTH_TEST)
    async def test_connect(self, connector, mock_api):
        await connector.connect()
        assert mock_api.called("/auth.test")
        assert mock_api.called("/users.info")
        connector.auth_info["user_id"] == "B061F7JD2"
        connector.user_info["user"] = "B061F7JD2"
        assert connector.bot_id == "B061F7JD2"

    async def test_connect_failure(self, connector, mock_api, caplog):
        await connector.connect()
        assert "The Slack Connector will not be available" in caplog.messages[0]

    @pytest.mark.add_response(
        "/users.info",
        "GET",
        {"ok": True, "user": {"id": "U01NK1K9L68", "name": "Test User"}},
        200,
    )
    async def test_lookup_username_user_not_present(self, connector, mock_api):
        user = await connector.lookup_username("U01NK1K9L68")
        assert mock_api.called("/users.info")
        assert user["id"] == "U01NK1K9L68"

    async def test_replace_usernames(self, connector):
        connector.known_users = {"U01NK1K9L68": {"name": "Test User"}}
        message = "hello <@U01NK1K9L68>"
        replaced_message = await connector.replace_usernames(message)
        assert replaced_message == "hello Test User"

    @pytest.mark.add_response(*CHAT_POST_MESSAGE)
    async def test_send_message(self, send_event, connector):
        event = events.Message(
            text="test", user="user", target="room", connector=connector
        )
        payload, response = await send_event(CHAT_POST_MESSAGE, event)
        assert payload == {
            "channel": "room",
            "text": "test",
            "username": "opsdroid",
            "icon_emoji": ":robot_face:",
        }
        assert response["ok"]

    @pytest.mark.add_response(*CHAT_POST_MESSAGE)
    async def test_send_message_inside_thread(self, send_event, connector):
        linked_event = events.Message(
            text="linked text", raw_event={"thread_ts": "1582838099.000600"}
        )
        event = events.Message(
            text="test",
            user="user",
            target="room",
            connector=connector,
            linked_event=linked_event,
            event_id="1582838099.000601",
        )
        payload, response = await send_event(CHAT_POST_MESSAGE, event)
        assert payload == {
            "channel": "room",
            "text": "test",
            "username": "opsdroid",
            "icon_emoji": ":robot_face:",
            "thread_ts": "1582838099.000600",
        }
        assert response["ok"]

    @pytest.mark.add_response(*CHAT_POST_MESSAGE)
    async def test_send_message_inside_thread_is_true(self, connector, send_event):
        connector.start_thread = True
        linked_event = events.Message(
            text="linked text", event_id="1582838099.000601", raw_event={}
        )
        event = events.Message(
            text="test",
            user="user",
            target="room",
            connector=connector,
            linked_event=linked_event,
        )
        payload, response = await send_event(CHAT_POST_MESSAGE, event)
        assert payload == {
            "channel": "room",
            "text": "test",
            "username": "opsdroid",
            "icon_emoji": ":robot_face:",
            "thread_ts": "1582838099.000601",
        }
        assert response["ok"]

    @pytest.mark.add_response(*CHAT_UPDATE_MESSAGE)
    async def test_edit_message(self, send_event, connector):
        linked_event = "1582838099.000600"

        event = events.EditedMessage(
            text="edited_message",
            user="user",
            target="room",
            connector=connector,
            linked_event=linked_event,
        )

        payload, response = await send_event(CHAT_UPDATE_MESSAGE, event)

        assert payload == {
            "channel": "room",
            "ts": "1582838099.000600",
            "text": "edited_message",
        }
        assert response["ok"]

    @pytest.mark.add_response(*CHAT_POST_MESSAGE)
    async def test_send_blocks(self, send_event, connector):
        event = Blocks(
            [{"type": "section", "text": {"type": "mrkdwn", "text": "*Test*"}}],
            target="room",
            connector=connector,
        )
        payload, response = await send_event(CHAT_POST_MESSAGE, event)
        assert payload == {
            "channel": "room",
            "username": "opsdroid",
            "blocks": '[{"type": "section", "text": {"type": "mrkdwn", "text": "*Test*"}}]',
            "icon_emoji": ":robot_face:",
        }
        assert response["ok"]

    @pytest.mark.add_response(*CHAT_UPDATE_MESSAGE)
    async def test_edit_blocks(self, send_event, connector):
        event = EditedBlocks(
            [{"type": "section", "text": {"type": "mrkdwn", "text": "*Test*"}}],
            user="user",
            target="room",
            connector=connector,
            linked_event="1358878749.000002",
        )
        payload, response = await send_event(CHAT_UPDATE_MESSAGE, event)
        assert payload == {
            "channel": "room",
            "blocks": '[{"type": "section", "text": {"type": "mrkdwn", "text": "*Test*"}}]',
            "ts": "1358878749.000002",
        }
        assert response["ok"]

    @pytest.mark.add_response(*REACTIONS_ADD)
    async def test_send_reaction(self, send_event, connector):
        message = events.Message(
            text="linked text",
            target="room",
            event_id="1582838099.000601",
            raw_event={"ts": 0},
        )
        event = events.Reaction("😀", target=message.target, linked_event=message)
        payload, response = await send_event(REACTIONS_ADD, event)
        assert payload == {
            "channel": "room",
            "name": "grinning_face",
            "timestamp": "1582838099.000601",
        }
        assert response["ok"]
        # TODO: Verify manually

    @pytest.mark.add_response(
        "/reactions.add", "POST", {"ok": False, "error": "invalid_name"}, 200
    )
    async def test_send_reaction_invalid_name(self, send_event):
        message = events.Message(
            text="linked text",
            target="room",
            event_id="1582838099.000601",
            raw_event={"ts": 0},
        )
        event = events.Reaction(
            "NOT_EMOJI", target=message.target, linked_event=message
        )
        await send_event(("/reactions.add",), event)

    @pytest.mark.add_response("/reactions.add", "POST", {"ok": False}, 200)
    async def test_send_reaction_unknown_error(self, send_event):
        message = events.Message(
            text="linked text",
            target="room",
            event_id="1582838099.000601",
            raw_event={"ts": 0},
        )
        event = events.Reaction(
            "NOT_EMOJI", target=message.target, linked_event=message
        )
        with pytest.raises(SlackApiError):
            _, response = await send_event(("/reactions.add",), event)
            assert not response["ok"]

    @pytest.mark.add_response(*CONVERSATIONS_CREATE)
    async def test_send_room_creation(self, send_event):
        event = events.NewRoom(name="new_room")
        payload, response = await send_event(CONVERSATIONS_CREATE, event)
        assert payload == {"name": "new_room"}
        assert response["ok"]

    @pytest.mark.add_response(*CONVERSATIONS_RENAME)
    async def test_send_room_name_set(self, send_event):
        event = events.RoomName(name="new_name_room", target="room")
        payload, response = await send_event(CONVERSATIONS_RENAME, event)
        assert payload == {"name": "new_name_room", "channel": "room"}
        assert response["ok"]

    @pytest.mark.add_response(*CONVERSATIONS_JOIN)
    async def test_join_room(self, send_event):
        event = events.JoinRoom(target="room")
        payload, response = await send_event(CONVERSATIONS_JOIN, event)
        assert payload == {"channel": "room"}
        assert response["ok"]

    @pytest.mark.add_response(*CONVERSATIONS_INVITE)
    async def test_send_user_invitation(self, send_event):
        event = events.UserInvite(user_id="U2345678901", target="room")
        payload, response = await send_event(CONVERSATIONS_INVITE, event)
        assert payload == {"channel": "room", "users": "U2345678901"}
        assert response["ok"]

    @pytest.mark.add_response(*CONVERSATIONS_SET_TOPIC)
    async def test_send_room_description(self, send_event):
        event = events.RoomDescription(description="Topic Update", target="room")
        payload, response = await send_event(CONVERSATIONS_SET_TOPIC, event)
        assert payload == {"channel": "room", "topic": "Topic Update"}
        assert response["ok"]

    @pytest.mark.add_response(*PINS_ADD)
    async def test_send_pin_added(self, send_event, connector):
        message = events.Message(
            "An important message",
            user="User McUserface",
            user_id="U9S8JGF45",
            target="room",
            connector=connector,
            event_id="1582838099.000600",
        )

        event = events.PinMessage(target="room", linked_event=message)

        payload, response = await send_event(PINS_ADD, event)
        assert payload == {"channel": "room", "timestamp": "1582838099.000600"}
        assert response["ok"]

    @pytest.mark.add_response(*PINS_REMOVE)
    async def test_send_pin_removed(self, send_event, connector):
        message = events.Message(
            "An important message",
            user="User McUserface",
            user_id="U9S8JGF45",
            target="an-existing-room",
            connector=connector,
            event_id="1582838099.000600",
        )

        event = events.UnpinMessage(target="room", linked_event=message)

        payload, response = await send_event(PINS_REMOVE, event)
        assert payload == {"channel": "room", "timestamp": "1582838099.000600"}
        assert response["ok"]
