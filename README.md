# trello-slack-hooks
Trello/Slack Hooks

Monitors Trello boards for created/updated cards and then posts messages to Slack as direct message or into a channel.

## Requirements
- Python 3
- `py-trello`
- `slackclient`

## Installation
Run `pipenv install` inside the project directory.

## Usage
Activate the virtual environment with `pipenv shell` and launch the script:
- `python trello_slack_hooks.py`.

To print a list of all Slack and Trello users and their IDs launch it with `-l` or `--list-users` as argument:
- `python trello_slack_hooks.py -l`.

## Configuration
Configuration is done via the file `settings.py`. Enter your Trello and Slack API credentials, set up a user mapping and define hooks.

For reference check out `settings.py.template`.

Notes for user mappings:
- The `display_name` in the user mappings is the name that will be used in the Slack message.

Notes for hooks:
- `trello_boards` can be set to `ALL_STARRED` to watch for changes in all boards, or to specific channel IDs (comma separated).
- `list_name` specifies the list that will be observed, only one list per hook is supported.
- Possible values for `triggers` are `createCard` for newly created cards and/or `updateCard` for updated cards.
- `type` in the slack message can be set to `direct` for a DM or to `channel` to post into a channel.
- `recipient` can be set to `CARD_ASSIGNMENT` to notify all assigned users, or to specific user or group IDs (comma separated).
