# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [In Development] - Unreleased

## [0.2.0] - 2026-11-09

### Fixed

- Old contracts are no longer shown as problems. A builder's contracts are looked at
  only from the moment he took the order, and only while he still has something to
  deliver. Records of such contracts that were made earlier disappear at the next sync.

### Added

- The Discord webhooks can be set in the Django admin ("Discord settings"). A value set
  there wins over `local.py`, and a change applies at once, without a restart.
- "My orders": the recipient of the delivery ("To", with a copy button), an instruction
  on how to deliver, the columns "Left to deliver" and "Total left"; the number of
  items that can be given back is in the "Discard" button.
- Search and filters above the order list (text, status, priority, level, only orders
  with free items); search and sorting on the page of the builder levels.
- Item icons, buttons that copy an order number or a price, colours for the access
  levels (Base, Middle, Senior).
- An emoji at the start of every Discord message that tells what kind of event it is.
- Dates with time are shown in the time zone of the browser.

### Changed

- Prices are whole ISK everywhere, the price field takes whole numbers only, and the
  Discord messages show "1 000 000 ISK".
- The message after "Sync contracts" no longer states a time; the page shows when the
  next automatic check is expected.
- The labels "Release" and "Open" of the order page are now "Release share" and "Not in a
  contract yet" (so that the translation of other apps does not replace the Russian
  one).

## [0.1.0] - 2026-11-03

First release.

### Added

- Corporate build orders: managers create orders (item from the EVE catalog, quantity,
  price per unit, priority, due date, access level, destination, note), change them,
  and delete (cancel) them
- Builders take a part of an order and can give it back until half of the time to the
  due date has passed; the order list and the "My orders" list can be sorted
- Builder access levels (Base, Middle, Senior): a builder sees and takes the orders up
  to his level
- Delivery through in-game item exchange contracts to the corporation, with the order
  number in the title; the plugin reads the corporation contracts with one ESI token
  (`esi-contracts.read_corporation_contracts.v1`), checks them (order number, price,
  item, quantity, builder) and credits the items when a contract is accepted
- Contract sync every minute, aligned with the ESI cache, and a "Sync contracts" button
- Manager tools: order details with history, release a share, credit by hand (also for
  a contract without the order number), builder levels, Management page
- Destinations: a list of stations and systems that managers add (public ESI), picked in
  the order form
- Discord notifications through webhooks: new, changed and deleted orders, items taken,
  items given back, contracts waiting for acceptance, items credited, contracts that
  cannot be counted, ESI token problems
- Item catalog from `django-eveuniverse` with a daily refresh
- Interface in English and Russian
