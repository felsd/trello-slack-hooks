import argparse
import os
import time
import traceback

import settings
from slack import WebClient
from trello import Board, TrelloClient


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
        boards = []
        stars = self.client.list_stars()
        for star in stars:
            board = Board(client=self.client, board_id=star.board_id)
            board.fetch()
            boards.append(board)
        return boards

    def get_lists_by_name(self, boards, name):
        """Returns lists in the given `boards` matching `name` (case insensitive)"""
        target_lists = []
        for board in boards:
            lists = board.all_lists()
            for lst in lists:
                if lst.name.lower() == name:
                    target_lists.append(lst)
        return target_lists

    def is_new_card(self, card, since):
        """The first 8 characters of the card id is a hexadecimal number.
        Converted to a decimal from hexadecimal, the timestamp is a Unix timestamp"""
        card_created = int(card.id[:8], 16)
        return card_created > since

    def is_moved_card(self, card, since):
        card_movements = card.list_movements()
        if len(card_movements) == 0:
            return False
        last_movement = card_movements[0]
        return time.mktime(last_movement["datetime"].timetuple()) > since


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

    def send_card_notification(self, card, slack_message):
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
            for recipient in recipients:
                mapping = get_user_mapping(slack_id=recipient[1:])
                if mapping is not None:
                    msg = message_text.replace(
                        "%recipient_name%", mapping["display_name"]
                    )
                    self.client.chat_postMessage(channel=recipient, text=msg)


class Hook:
    def __init__(self, hook):
        self.last_check = int(time.time())
        self.trello_boards = hook["trello_boards"]
        self.list_name = hook["list_name"]
        self.triggers = [x.strip() for x in hook["triggers"].split(",")]
        self.slack_message = hook["slack_message"]

    def execute(self, trello_api, slack_api):
        if self.trello_boards == "ALL_STARRED":
            boards = trello_api.get_starred_boards()
        else:
            boards = [
                Board(client=trello_api.client, board_id=x.strip())
                for x in self.trello_boards.split(",")
            ]
            for board in boards:
                board.fetch()
        target_lists = trello_api.get_lists_by_name(boards, self.list_name)
        for target_list in target_lists:
            cards = target_list.list_cards()
            for card in cards:
                check_funcs = []
                if "created" in self.triggers:
                    check_funcs.append(trello_api.is_new_card)
                if "moved" in self.triggers:
                    check_funcs.append(trello_api.is_moved_card)
                for func in check_funcs:
                    if func(card, self.last_check):
                        slack_api.send_card_notification(card, self.slack_message)
                        break
        self.last_check = int(time.time())


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
    # Start Hook execution
    hooks = [Hook(x) for x in settings.HOOKS]
    while True:
        try:
            for hook in hooks:
                hook.execute(trello_api, slack_api)
        except KeyboardInterrupt:
            os._exit(0)
        except Exception:
            traceback.print_exc()
        finally:
            time.sleep(settings.CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
