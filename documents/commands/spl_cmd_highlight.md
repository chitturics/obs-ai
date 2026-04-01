---
 command: highlight
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/highlight
 title: highlight
 download_date: 2026-02-03 09:09:04
---

 # highlight

Highlights specified terms in the events list. Matches a string or list of strings and highlights them in the display in Splunk Web. The matching is not case sensitive.

highlight <string>...

#### Required arguments

The highlight command is a distributable streaming command. See Command types.

The string that you specify must be a field value. The string cannot be a field name.

You must use the highlight command in a search that keeps the raw events and displays output on the Events tab. You cannot use the highlight command with commands, such as stats which produce calculated or generated results.

#### Example 1:

Highlight the terms "login" and "logout".

#### Example 2:

Highlight the phrase "Access Denied".
 