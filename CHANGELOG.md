# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [In Development] - Unreleased

## [0.1.0] - Unreleased

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