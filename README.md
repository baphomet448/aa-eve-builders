# EVE Builders for Alliance Auth

[Русская версия](README.ru.md)

![License](https://img.shields.io/badge/license-GPLv3-green)
![python](https://img.shields.io/badge/python-3.10%2B-informational)
![django](https://img.shields.io/badge/django-5.2-informational)

Corporate build orders for [Alliance Auth](https://gitlab.com/allianceauth/allianceauth)
(AA). Managers post orders ("20 Punishers at 1.5M each, due on Friday"), builders
take a part of an order, build it and deliver it with an ordinary in-game item
exchange contract to the corporation. The plugin reads the corporation contracts,
checks them against the order, and credits the builder when the contract is
accepted. Everyone is kept informed through Discord.

This plugin is a rewrite for Alliance Auth of the Java web application
[eve-builders](https://github.com/AntonAzarenko/eve-builders) by AntonAzarenko. No
code was copied; the idea and the workflow are his. Thank you!

> [!IMPORTANT]
>
> **This app needs Alliance Auth v5**, a running Celery worker **and Celery beat**
> (the contracts are checked by a scheduled task).

______________________________________________________________________

- [Features](#features)
- [How it works](#how-it-works)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [Install the package](#install-the-package)
  - [Scheduled tasks](#scheduled-tasks)
  - [ESI scope](#esi-scope)
  - [Permissions](#permissions)
  - [First setup in the web interface](#first-setup-in-the-web-interface)
- [Configuration](#configuration)
- [Discord notifications](#discord-notifications)
- [Contract rules](#contract-rules)
- [Management commands](#management-commands)
- [Updating](#updating)
- [Known limitations](#known-limitations)
- [Development](#development)
- [Credits and license](#credits-and-license)

______________________________________________________________________

## Features

- **Orders**: item from the EVE catalog, quantity, price per unit, priority, due
  date, access level, delivery place and a note. Order numbers look like
  `N20261101-1` (date and the number of the day).
- **Builders** take any part of an order and can give it back until half of the time
  between the creation and the due date has passed. After that only a manager can
  take it back.
- **Access levels** Base, Middle and Senior: a builder does not see orders above
  his level.
- **Delivery through contracts**: the builder creates an item exchange contract to
  the corporation with the order number in the title. The plugin credits it when it
  is accepted in the game. No manual book-keeping.
- **My orders** page with what was taken, what waits for acceptance, what is done,
  prices and the due dates, and the contracts that could not be counted and why.
- **Manager tools**: order details with history, edit, delete (cancel), release a
  share, credit by hand (also a contract without the order number), builder levels,
  places to deliver to, and a Management page that shows what needs attention.
- **Discord** notifications through webhooks.
- **English and Russian** interface.
- **Convenience**: search and filters above the order list, item icons, buttons that copy
  an order number or a price, and dates in the time zone of your browser.
- **Management**: three tabs (contracts, statistics with the cost to buy out the active
  orders, and the history with a filter and pages).

## How it works

1. A manager creates an order. Discord gets a message.
1. A builder opens **Corporate orders** and takes a part of it.
1. The builder builds the items and creates an **item exchange contract to the
   corporation** (see [Contract rules](#contract-rules)): the order number in the
   title, the price is the price per unit multiplied by the quantity.
1. Within a few minutes the plugin sees the contract and the order shows the share as
   **Under review**.
1. When someone accepts the contract in the game, the plugin credits the items,
   shows who accepted it, and reports it in Discord. When everything is credited, the
   order is **Done**.

## Installation

### Requirements

- Alliance Auth 5 (tested with 5.4), Python 3.10 or newer
- [django-eveuniverse](https://pypi.org/project/django-eveuniverse/) 2.2 or newer
  (the item catalog). If your Auth has it already, nothing to do.
- Celery worker and **Celery beat** running

### Install the package

There is no PyPI release: install the wheel from the release page. Activate the virtual
environment of your Auth first.

```shell
pip install https://github.com/baphomet448/aa-eve-builders/releases/download/v0.3.0/aa_eve_builders-0.3.0-py3-none-any.whl
```

Add the apps to `INSTALLED_APPS` in your `local.py` (`eveuniverse` only if it is not
there yet):

```python
INSTALLED_APPS += [
    "eveuniverse",
    "evebuilders",
]
```

Run the migrations and restart Auth:

```shell
python manage.py migrate
python manage.py collectstatic --noinput
```

Then restart the services (for example `supervisorctl restart myauth:` on a standard
installation).

#### Docker (allianceauth-docker)

The image of Auth has no `git`, so use the wheel too. Add this line to
`conf/requirements.txt`:

```text
aa-eve-builders @ https://github.com/baphomet448/aa-eve-builders/releases/download/v0.3.0/aa_eve_builders-0.3.0-py3-none-any.whl
```

Add the `INSTALLED_APPS` lines and the scheduled tasks to `conf/local.py`. Then rebuild
the image and **recreate** the containers (`docker compose restart` is not enough: it
neither changes the image nor reads `.env` again), and run the migrations in the
container:

```shell
docker compose build
docker compose --env-file=.env up -d --force-recreate
docker compose exec allianceauth_gunicorn bash
auth migrate
auth collectstatic --noinput
```

### Scheduled tasks

Add these two tasks to `CELERYBEAT_SCHEDULE` in `local.py` and restart Celery beat:

```python
CELERYBEAT_SCHEDULE["evebuilders_sync_catalog"] = {
    "task": "evebuilders.tasks.sync_catalog",
    "schedule": crontab(minute="30", hour="4"),
}

CELERYBEAT_SCHEDULE["evebuilders_sync_contracts"] = {
    "task": "evebuilders.tasks.sync_contracts",
    "schedule": crontab(minute="*"),
}
```

- `sync_catalog` refreshes the item catalog once a day (04:30 UTC here).
- `sync_contracts` runs **every minute**, but it reads ESI only when ESI has fresh data
  (the contract list is cached by ESI for about five minutes) and not more often than
  the minimum interval. Most runs do nothing and report `not_yet`: that is normal.

### ESI scope

The plugin reads the contracts of the corporation with the token of **one corporation
member**; no in-game role is needed. The CCP application of your Auth
(<https://developers.eveonline.com/>) must allow this scope:

```text
esi-contracts.read_corporation_contracts.v1
```

Add it to the application if it is not there yet.

### Permissions

Give these permissions in the Auth admin to groups or states. They appear as
"EVE Builders ... | general | ...":

| Permission                   | Who      | What it allows                        |
| ---------------------------- | -------- | ------------------------------------- |
| `evebuilders.builder_access` | builders | View and take corporate build orders  |
| `evebuilders.manage_access`  | managers | Manage orders and the plugin settings |

Menu entries ("Corporate orders" and "My orders") are shown only to people with one of
them. If you group the menu in folders (Auth admin, Menu), put them in a folder of
your choice.

### First setup in the web interface

A manager does this once (the **Settings** button of the plugin):

1. **ESI and catalog, ESI connection**: press **Connect** with a character that is in the
   corporation. The corporation contracts are read with this token.
1. **ESI and catalog, Item catalog**: press **Update catalog** and wait a few minutes for
   the items to load (it also refreshes by itself every day).
1. **Builder levels**: set the levels of the builders (Base by default).
1. **Stations**: add the places orders are delivered to (search a system by a part of
   its name, pick a station, or add a system with the name of a structure). While the
   list is empty, the destination of an order is free text.

Then try the **Create order** button.

## Configuration

All settings are optional. Put them in `local.py`.

| Setting                                     | Default                                | Meaning                                                        |
| ------------------------------------------- | -------------------------------------- | -------------------------------------------------------------- |
| `EVEBUILDERS_CATALOG_CATEGORY_IDS`          | `[4, 6, 7, 8, 18, 22, 32, 65, 66, 87]` | EVE categories kept in the item catalog                        |
| `EVEBUILDERS_CATALOG_GROUP_IDS`             | `[]`                                   | Extra single groups (for example `1136`, Fuel Block)           |
| `EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES`  | `15`                                   | Shortest time between two catalog updates                      |
| `EVEBUILDERS_SYNC_MIN_INTERVAL_SECONDS`     | `60`                                   | Shortest time between two contract syncs (button and schedule) |
| `EVEBUILDERS_DISCORD_NEW_ORDER_WEBHOOK_URL` | empty                                  | Webhook for new, changed and deleted orders                    |
| `EVEBUILDERS_DISCORD_NEW_ORDER_THREAD_ID`   | empty                                  | Thread ID of that channel, if the webhook posts into a thread  |
| `EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL`  | empty                                  | Webhook for the reports about contracts and deliveries         |
| `EVEBUILDERS_DISCORD_COMPLETE_THREAD_ID`    | empty                                  | Thread ID of that channel                                      |
| `EVEBUILDERS_DISCORD_NOTIFY_TAKEN`          | `True`                                 | Announce that a builder took a part of an order                |

The default categories are Material, Ship, Module, Charge, Drone, Deployable,
Subsystem, Structure, Structure Module and Fighter.

## Discord notifications

Messages go to three channels, each with its own webhook: **New orders**, **On review**
and **Everything else**. Set the webhooks in the plugin: **Settings, Discord** (managers
only). The address of a webhook is a secret (whoever has it can write to the channel), so
it is never shown again: the page shows only the end of it, an empty field keeps the saved
address, and only addresses of Discord are accepted. A change applies at once, no restart
is needed. The button "Send a test message" posts to a channel without the mention of
everyone.

The same page has a table of the 11 kinds of messages. For each kind choose the channel,
or "Off", and say whether the message mentions @everyone. A message that goes to a channel
without a webhook is not sent (the page warns about it).

Until the table is saved, the messages go where they went in the earlier versions, so an
update changes nothing by itself:

| Kind of message                                            | Channel (by default) |
| ---------------------------------------------------------- | -------------------- |
| New order, order changed, order deleted                    | New orders           |
| A builder took a part, gave it back, a manager released it | Everything else      |
| A contract waits for acceptance, was accepted and credited | Everything else      |
| Credited by hand, a contract cannot be counted             | Everything else      |
| The ESI token stopped working                              | Everything else      |

An empty webhook of "New orders" or "Everything else" falls back to the setting of
`local.py` (`EVEBUILDERS_DISCORD_NEW_ORDER_*` and `EVEBUILDERS_DISCORD_COMPLETE_*`, see
Configuration). The third channel has no setting in `local.py`. The webhooks can also be
set in the Django admin (EVE BUILDERS, Discord settings).

The thread ID is optional. It is needed only when the webhook has to post into a thread
(a forum channel needs it). Switch on the developer mode in Discord, then copy the ID of
the thread. Create the webhook in the parent channel of the thread.

Messages are sent in the background with several retries when Discord is busy. They are
written in **Russian**, and each starts with an emoji that tells the kind of event. The
command below posts a test message to the channels that have a webhook (it mentions
@everyone):

```shell
python manage.py evebuilders_test_notification
```

| Channel   | What is sent                                                                                                                                                                                  |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New order | an order was created, changed or deleted                                                                                                                                                      |
| Complete  | a builder took a part, gave it back, a manager released it; a contract waits for acceptance, was accepted and credited, or cannot be counted (with the reason); the ESI token stopped working |

## Contract rules

A contract is counted when **all** of this is true:

- it is an **item exchange** contract **to the corporation** (not to a person);
- the title contains the **order number**, for example `N20261101-1` (other text next to
  it is fine; two different numbers are refused);
- it was created by a character on the Auth account of a builder who **took** this
  order;
- it **includes** the item of the order (other items in the same contract are
  ignored);
- the **price** equals the price per unit multiplied by the quantity of that item (a
  difference of 0.01 ISK is allowed);
- the quantity is not more than what the builder still has to deliver.

A valid contract is **Under review** until someone accepts it, then it is **credited**.
A contract that does not fit is shown to the builder under "Contracts that could not be
counted" with the reason, and to the managers on the Management page; a manager can
credit it by hand after looking at it. A contract that is deleted or expires leaves the
list by itself.

> [!NOTE]
>
> ESI caches the corporation contract list for about five minutes. A new contract, or
> one that was just accepted, shows up after ESI refreshes its answer. "My orders"
> shows when the next automatic check is expected.

## Management commands

```shell
python manage.py evebuilders_sync_catalog        # update the item catalog now
python manage.py evebuilders_sync_contracts      # read and apply the contracts now
python manage.py evebuilders_show_contracts      # show the corporation contracts as ESI gives them
python manage.py evebuilders_load_systems        # (re)load the names of the solar systems
python manage.py evebuilders_test_notification   # send a test message to Discord
```

Every command has `--help`. The names of the solar systems (used to search a system by
a part of its name) are loaded by themselves at the first search.

## Updating

```shell
pip install -U https://github.com/baphomet448/aa-eve-builders/releases/download/<version>/aa_eve_builders-<version>-py3-none-any.whl
python manage.py migrate
python manage.py collectstatic --noinput
```

Restart the services afterwards. If an update changes the menu entries, pages of Auth can
show an error until `python manage.py migrate` has been run: run it and reload.

With Docker change the version in the line of `conf/requirements.txt` (the tag and the
name of the file), then run `docker compose build`,
`docker compose --env-file=.env up -d --force-recreate`, and `auth migrate` and
`auth collectstatic --noinput` in the container.

## Known limitations

- One corporation and one ESI token. The orders are corporate; personal orders are
  planned.
- The public ESI knows only NPC stations. For player structures (and wormholes) a
  manager adds the system and types the structure name.
- Discord messages are in Russian only.
- Dates and deadlines are calculated in UTC.
- Status, priority and access level names (Done, High, Senior ...) are kept in English
  on purpose.

## Development

```shell
python runtests.py evebuilders -v 2   # or: tox
```

Translations (needs GNU gettext):

```shell
cd evebuilders
django-admin makemessages -l ru --no-obsolete --add-location=file -i "tests/*"
django-admin compilemessages
```

The compiled `django.mo` is kept in the repository, so a server does not need gettext.
Issues and pull requests are welcome.

## Credits and license

- The idea and the workflow come from the Java application
  [eve-builders](https://github.com/AntonAzarenko/eve-builders) by AntonAzarenko.
- The project was started from the Alliance Auth Example Plugin (GitHub version).
- Licensed under the **GNU General Public License v3.0 or later** (GPL-3.0-or-later), see [LICENSE](LICENSE).
