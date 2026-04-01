---
 command: surrounding
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Surrounding
 title: surrounding
 download_date: 2026-02-03 09:18:37
---

 ## Syntax
surrounding id=<event-id> timebefore=<int> timeafter=<int> searchkeys=<key-list> <int:maxresults> readlevel=<readlevel-int> <index-specifier> <int>:<int> (<string> )* 0|1|2|3

## Description
Finds events surrounding the event specified by event-id filtered by the search keys. a splunk internal event id a list of keys that are ANDed to provide a filter for surrounding command How deep to read the events, 0 : just source/host/sourcetype, 1 : 0 with _raw, 2 : 1 with kv, 3 2 with types ( deprecated in 3.2 )


## Syntax
surrounding id=<event-id> timebefore=<int> timeafter=<int> searchkeys=<key-list> <int:maxresults> readlevel=<readlevel-int> <index-specifier> <int>:<int> (<string> )* 0|1|2|3

## Description
Finds events surrounding the event specified by event-id filtered by the search keys. a splunk internal event id a list of keys that are ANDed to provide a filter for surrounding command How deep to read the events, 0 : just source/host/sourcetype, 1 : 0 with _raw, 2 : 1 with kv, 3 2 with types ( deprecated in 3.2 )
 