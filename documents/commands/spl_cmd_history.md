---
 command: history
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/history
 title: history
 download_date: 2026-02-03 09:09:12
---

 # history

Use this command to view your search history in the current application. This search history is presented as a set of events or as a table.

| history [events=<bool>]

#### Required arguments

#### Optional arguments

Fields returned when events=false.

The history command is a generating command and should be the first command in the search. Generating commands use a leading pipe character.

The history command returns your search history only from the application where you run the command.

#### Return search history in a table

Return a table of the search history. You do not have to specify events=false, since that this the default setting.

#### Return search history as events

Return the search history as a set of events.
 