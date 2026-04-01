---
 command: iconify
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/iconify
 title: iconify
 download_date: 2026-02-03 09:09:17
---

 # iconify

Causes Splunk Web to display an icon for each different value in the list of fields that you specify.

The iconify command adds a field named _icon to each event. This field is the hash value for the event. Within Splunk Web, a different icon for each unique value in the field is displayed in the events list. If multiple fields are listed, the UI displays a different icon for each unique combination of the field values.

iconify <field-list>

#### Required arguments

The iconify command is a distributable streaming command. See Command types.

#### 1. Display a different icon for each eventtype

#### 2. Display a different icon for unique pairs of field values

Display a different icon for unique pair of clientip and method values.

Here is how Splunk Web displays the results in your Events List:
 