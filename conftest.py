"""Shared pytest fixtures with realistic mock Spond data."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from server import SpondService

# --- Mock data: groups ---
# Spond gives each kid a separate member ID per group, spells names differently per
# group, and returns every member with guardians and contact details.

PROFILE_ID = "PROFILE_OLA"
PARENT = {
    "id": "GUARDIAN_OLA",
    "firstName": "Ola",
    "lastName": "Nordmann",
    "email": "ola@example.com",
    "phoneNumber": "+4799999999",
    "profile": {"id": PROFILE_ID},
}
OTHER_PARENT = {
    "id": "GUARDIAN_KARI",
    "firstName": "Kari",
    "lastName": "Hansen",
    "email": "kari.hansen@example.com",
    "phoneNumber": "+4791111111",
    "profile": {"id": "PROFILE_KARI"},
}
MOCK_PROFILE = {"id": PROFILE_ID, "firstName": "Ola", "primaryEmail": "ola@example.com"}

MOCK_GROUPS = [
    {
        "id": "GROUP_FJORDVIK",
        "name": "Fjordvik FK G2013",
        "members": [
            {
                "id": "MEMBER_OLIVER",
                "firstName": "Oliver Nordmann",
                "lastName": "Nordmann",
                "roles": ["member"],
                "guardians": [PARENT],
            },
            {
                "id": "MEMBER_NOAH",
                "firstName": "Noah",
                "lastName": "Hansen",
                "email": "noah@example.com",
                "phoneNumber": "+4792222222",
                "guardians": [OTHER_PARENT],
            },
            {
                "id": "MEMBER_PARENT",
                "firstName": "Ola",
                "lastName": "Nordmann",
                "email": "ola@example.com",
                "roles": ["admin"],
            },
            {
                "id": "MEMBER_COACH",
                "firstName": "Trener",
                "lastName": "Hansen",
                "roles": ["admin"],
            },
        ],
        "subGroups": [],
    },
    {
        "id": "GROUP_SOLVIK",
        "name": "Solvik IL 2017",
        "members": [
            {
                "id": "MEMBER_EMMA",
                "firstName": "Emma",
                "lastName": "Nordmann",
                "roles": ["member"],
                "guardians": [PARENT],
            },
            {
                "id": "MEMBER_PARENT_B",
                "firstName": "Ola",
                "lastName": "Nordmann",
                "email": "ola@example.com",
                "roles": ["admin"],
            },
        ],
        "subGroups": [],
    },
    {
        "id": "GROUP_NORDVIK",
        "name": "Nordvik skole kull 2014",
        "members": [
            {
                "id": "MEMBER_OLIVER_SKOLE",
                "firstName": "Oliver",
                "lastName": "Nordmann",
                "roles": ["member"],
                "guardians": [PARENT],
            },
        ],
        "subGroups": [],
    },
]

# Events carry the whole group, members included.
RECIPIENTS_FJORDVIK = {"group": {"id": "GROUP_FJORDVIK", "members": MOCK_GROUPS[0]["members"]}}

# --- Mock data: events ---

MOCK_EVENTS_FJORDVIK = [
    {
        "id": "EVT_TRENING_1",
        "heading": "Trening",
        "type": "RECURRING",
        "startTimestamp": "2026-02-23T17:00:00.000+00:00",
        "endTimestamp": "2026-02-23T18:30:00.000+00:00",
        "cancelled": False,
        "description": "Vanlig trening, ta med drikke",
        "location": {
            "feature": "Fjordvik kunstgress",
            "address": "Idrettsvegen 12, 0001 Fjordvik",
            "latitude": 59.9127,
            "longitude": 10.7461,
        },
        "responses": {
            "acceptedIds": ["MEMBER_OLIVER"],
            "declinedIds": [],
            "unansweredIds": ["MEMBER_COACH", "MEMBER_NOAH"],
            "waitinglistIds": [],
            "unconfirmedIds": [],
        },
        "recipients": RECIPIENTS_FJORDVIK,
    },
    {
        "id": "EVT_KAMP_1",
        "heading": "Seriekamp vs Havnes",
        "type": "EVENT",
        "startTimestamp": "2026-02-25T18:00:00.000+00:00",
        "endTimestamp": "2026-02-25T19:30:00.000+00:00",
        "rsvpDate": "2026-02-24T12:00:00.000+00:00",
        "cancelled": False,
        "description": "Oppmøte 17:30. Husk drakt og leggskinn.",
        "location": {
            "feature": "Havnes Arena",
            "address": "Sjøgata 5, 0002 Havnes",
            "latitude": 59.8765,
            "longitude": 10.8123,
        },
        "responses": {
            "acceptedIds": [],
            "declinedIds": [],
            "unansweredIds": ["MEMBER_OLIVER"],
            "waitinglistIds": [],
            "unconfirmedIds": [],
        },
        "recipients": {"group": {"id": "GROUP_FJORDVIK"}},
    },
]

MOCK_EVENTS_SOLVIK = [
    {
        "id": "EVT_FOTBALL_1",
        "heading": "Trening",
        "type": "RECURRING",
        "startTimestamp": "2026-02-24T16:30:00.000+00:00",
        "endTimestamp": "2026-02-24T17:30:00.000+00:00",
        "cancelled": False,
        "description": "",
        "location": {
            "feature": "Nordvik minibane",
        },
        "responses": {
            "acceptedIds": ["MEMBER_EMMA"],
            "declinedIds": [],
            "unansweredIds": [],
            "waitinglistIds": [],
            "unconfirmedIds": [],
        },
        "recipients": {"group": {"id": "GROUP_SOLVIK"}},
    },
]

MOCK_EVENT_CANCELLED = {
    "id": "EVT_CANCELLED",
    "heading": "Trening",
    "type": "RECURRING",
    "startTimestamp": "2026-02-26T17:00:00.000+00:00",
    "endTimestamp": "2026-02-26T18:30:00.000+00:00",
    "cancelled": True,
    "description": "Avlyst pga. snø",
    "location": {"feature": "Fjordvik kunstgress"},
    "responses": {
        "acceptedIds": [],
        "declinedIds": [],
        "unansweredIds": [],
        "waitinglistIds": [],
        "unconfirmedIds": [],
    },
    "recipients": {"group": {"id": "GROUP_FJORDVIK"}},
}

MOCK_EVENT_DETAIL = {
    **MOCK_EVENTS_FJORDVIK[1],
    "description": "Oppmøte 17:30. Husk drakt og leggskinn.\n\nRød drakt, hvite shorts.",
    "rsvpDate": "2026-02-24T12:00:00.000+00:00",
}

MOCK_EVENTS_NORDVIK = [
    {
        "id": "EVT_SKOLE_1",
        "heading": "Foreldremøte",
        "type": "EVENT",
        "startTimestamp": "2026-02-27T17:00:00.000+00:00",
        "endTimestamp": "2026-02-27T18:00:00.000+00:00",
        "cancelled": False,
        "description": "",
        "location": {"feature": "Nordvik skole"},
        "responses": {
            "acceptedIds": [],
            "declinedIds": [],
            "unansweredIds": [],
            "waitinglistIds": ["MEMBER_OLIVER_SKOLE"],
            "unconfirmedIds": [],
        },
        "recipients": {"group": {"id": "GROUP_NORDVIK"}},
    },
]

MOCK_ALL_EVENTS = MOCK_EVENTS_FJORDVIK + MOCK_EVENTS_SOLVIK + MOCK_EVENTS_NORDVIK

MOCK_POSTS = [
    {
        "id": "POST_1",
        "body": "Husk å ta med egne drikkebokser til kampen på lørdag. Vi har ikke engangskopper.",
        "timestamp": "2026-02-22T10:30:00.000+00:00",
        "groupId": "GROUP_FJORDVIK",
        "createdByProfile": {
            "id": "MEMBER_COACH",
            "firstName": "Trener",
            "lastName": "Hansen",
            "email": "trener@example.com",
        },
        "comments": [
            {"id": "COMMENT_1", "body": "Notert!", "timestamp": "2026-02-22T11:00:00.000+00:00"},
        ],
    },
    {
        "id": "POST_2",
        "body": "Treningene flyttes innendørs fra neste uke pga. vær. Møt opp i hallen kl 17:00.",
        "timestamp": "2026-02-21T14:00:00.000+00:00",
        "groupId": "GROUP_FJORDVIK",
        "createdByProfile": {
            "id": "MEMBER_COACH",
            "firstName": "Trener",
            "lastName": "Hansen",
        },
        "comments": [],
    },
    {
        "id": "POST_3",
        "body": "Velkommen til ny sesong! Første trening er mandag.",
        "timestamp": "2026-02-20T09:00:00.000+00:00",
        "groupId": "GROUP_SOLVIK",
        "createdByProfile": {
            "id": "MEMBER_PARENT_B",
            "firstName": "Ola",
            "lastName": "Nordmann",
        },
        "comments": [
            {"id": "COMMENT_2", "body": "Hurra!", "timestamp": "2026-02-20T09:30:00.000+00:00"},
            {"id": "COMMENT_3", "body": "Gleder oss!", "timestamp": "2026-02-20T10:00:00.000+00:00"},
        ],
    },
]


@pytest.fixture
def mock_spond_client():
    """Mock Spond client with pre-configured responses."""
    client = AsyncMock()
    client.get_profile = AsyncMock(return_value=MOCK_PROFILE)
    client.get_groups = AsyncMock(return_value=MOCK_GROUPS)

    async def mock_get_events(min_start=None, max_end=None, group_id=None, **kwargs):
        if group_id == "GROUP_FJORDVIK":
            return MOCK_EVENTS_FJORDVIK
        elif group_id == "GROUP_SOLVIK":
            return MOCK_EVENTS_SOLVIK
        elif group_id == "GROUP_NORDVIK":
            return MOCK_EVENTS_NORDVIK
        return MOCK_ALL_EVENTS

    client.get_events = AsyncMock(side_effect=mock_get_events)

    async def mock_get_event(uid):
        if uid == MOCK_EVENT_DETAIL["id"]:
            return MOCK_EVENT_DETAIL
        for e in MOCK_ALL_EVENTS:
            if e["id"] == uid:
                return e
        raise KeyError(uid)

    client.get_event = AsyncMock(side_effect=mock_get_event)
    client.change_response = AsyncMock(return_value={"acceptedIds": ["MEMBER_OLIVER"], "declinedIds": []})

    async def mock_get_posts(group_id=None, max_posts=20, include_comments=True):
        posts = MOCK_POSTS
        if group_id:
            posts = [p for p in posts if p.get("groupId") == group_id]
        return posts[:max_posts]

    client.get_posts = AsyncMock(side_effect=mock_get_posts)
    client.get_messages = AsyncMock(
        return_value=[
            {
                "id": "CHAT_1",
                "title": "Foreldre G2013",
                "lastMessage": {
                    "body": "Hvem kjører?",
                    "timestamp": "2026-02-22T12:00:00.000+00:00",
                    "sender": {"firstName": "Kari", "lastName": "Hansen", "email": "kari.hansen@example.com"},
                },
                "participants": [OTHER_PARENT, PARENT],
            }
        ]
    )
    client.get_msg_history = AsyncMock(
        return_value=[
            {
                "body": "Jeg kan kjøre",
                "timestamp": "2026-02-22T12:05:00.000+00:00",
                "sender": {"firstName": "Kari", "phoneNumber": "+4791111111"},
            }
        ]
    )
    client.clientsession = MagicMock()
    client.clientsession.close = AsyncMock()
    return client


@pytest.fixture
def service(mock_spond_client):
    """SpondService that finds the kids through guardian links (no KIDS_CONFIG)."""
    return SpondService(client=mock_spond_client)


@pytest.fixture
def service_only_emma(mock_spond_client):
    """SpondService with KIDS_CONFIG limiting the kids to Emma."""
    return SpondService(client=mock_spond_client, kids_config=["Emma"])
