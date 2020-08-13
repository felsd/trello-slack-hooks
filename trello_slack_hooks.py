import argparse
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import settings
from slack import WebClient
from trello import Board, Card, TrelloClient


def line(c="-"):
    rows, cols = os.popen("stty size", "r").read().split()
    print(c * int(cols))


def get_user_mapping(trello_id=None, slack_id=None):
    if trello_id is None and slack_id is None:
        raise Exception("Neither slack id nor trello id provided")
    for mapping in settings.USER_MAPPINGS:
        if trello_id and mapping["trello_id"] == trello_id:
            return mapping
        elif slack_id and mapping["slack_id"] == slack_id:
            return mapping
    print(
        "WARNING: No user mapping for "
        f"{next(x for x in [trello_id, slack_id] if x is not None)}"
    )


class TrelloApi:
    def __init__(self):
        self.client = TrelloClient(
            api_key=settings.TRELLO_API_KEY, api_secret=settings.TRELLO_API_SECRET
        )

    def print_users(self):
        """Prints users of all organizations"""
        line()
        print("Trello users:")
        line()
        users = set()
        organizations = self.client.list_organizations()
        for org in organizations:
            users.update([f"{x.full_name}: {x.id}" for x in org.get_members()])
        for user in users:
            print(user)

    def get_starred_boards(self):
        """Returns all starred boards"""
        return self.client.list_boards(board_filter="starred")

    def fetch_cards(self, triggers, board, target_list, since):
        result = set()
        cards = board.fetch_actions(triggers, since=since)
        for card_data in cards:
            list_name = (
                card_data["data"]["listAfter"]["name"]
                if "listAfter" in card_data["data"]
                else card_data["data"]["list"]["name"]
            )
            if list_name.lower() != target_list.lower():
                continue
            card = Card(board, card_data["data"]["card"]["id"])
            card.fetch(eager=False)
            card.card_action = (
                "created" if card_data["type"] == "createCard" else "updated"
            )
            result.add(card)
        return result


class SlackApi:
    def __init__(self):
        self.client = WebClient(token=settings.SLACK_API_KEY)

    def print_users(self):
        """Prints all known Slack users which aren't bots and have a real name"""
        line()
        print("Slack users:")
        line()
        slack_users = self.client.users_list()
        for user in slack_users["members"]:
            if not user["is_bot"] and "real_name" in user:
                print(f"{user['real_name']}: {user['id']}")

    def send_message(self, card, slack_message):
        """Notifies a user or channel about a new card via Slack message"""
        if slack_message["recipient"] == "CARD_ASSIGNMENT":
            recipients = [
                f"@{get_user_mapping(trello_id=x)['slack_id']}" for x in card.member_id
            ]
        else:
            prefix = "@" if slack_message["type"] == "direct" else "#"
            recipients = [
                f"{prefix}{x.strip()}" for x in slack_message["recipient"].split(",")
            ]
        if len(recipients) > 0:
            message_text = slack_message["message"]
            message_text = message_text.replace("%board_name%", card.board.name)
            message_text = message_text.replace("%card_title%", card.name)
            message_text = message_text.replace("%card_url%", card.shortUrl)
            message_text = message_text.replace("%card_action%", card.card_action)
            for recipient in recipients:
                mapping = get_user_mapping(slack_id=recipient[1:])
                if mapping is not None:
                    msg = message_text.replace(
                        "%recipient_name%", mapping["display_name"]
                    )
                self.client.chat_postMessage(channel=recipient, text=msg)
                print(
                    "Sent a message to "
                    f"{mapping['display_name'] if mapping else recipient} "
                    f"[{card.name}]"
                )


class Hook:
    def __init__(self, hook):
        self.last_check = datetime.utcnow().replace(microsecond=0).isoformat()
        self.trello_boards = hook["trello_boards"]
        self.list_name = hook["list_name"]
        self.triggers = [x.strip() for x in hook["triggers"].split(",")]
        self.slack_message = hook["slack_message"]
        self.executor = ThreadPoolExecutor()

    def execute(self, trello_api, slack_api, starred_boards):
        if self.trello_boards == "ALL_STARRED":
            boards = starred_boards
        else:
            boards = [
                Board(client=trello_api.client, board_id=x.strip())
                for x in self.trello_boards.split(",")
            ]
        futures = []
        for board in boards:
            futures.append(
                self.executor.submit(
                    trello_api.fetch_cards,
                    self.triggers,
                    board,
                    self.list_name,
                    f"{self.last_check}Z",
                )
            )
        for future in as_completed(futures):
            cards = future.result()
            for card in cards:
                slack_api.send_message(card, self.slack_message)
        self.last_check = datetime.utcnow().replace(microsecond=0).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Trello/Slack Hooks")
    parser.add_argument("-l", "--list-users", action="store_true")
    args = parser.parse_args()
    # Instantiate APIs
    trello_api = TrelloApi()
    slack_api = SlackApi()
    # List users
    if args.list_users:
        trello_api.print_users()
        slack_api.print_users()
        os._exit(0)
    # Instantiate Hooks and start main loop
    hooks = [Hook(x) for x in settings.HOOKS]
    any_starred = any(x.trello_boards == "ALL_STARRED" for x in hooks)
    executor = ThreadPoolExecutor()
    while True:
        try:
            # Fetch starred boards inside the loop as they might have changed,
            # but only fetch them once
            starred_boards = None
            if any_starred:
                starred_boards = trello_api.get_starred_boards()
            # Hook execution
            futures = []
            for hook in hooks:
                futures.append(
                    executor.submit(hook.execute, trello_api, slack_api, starred_boards)
                )
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            os._exit(0)
        except Exception:
            traceback.print_exc()
        finally:
            time.sleep(settings.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
