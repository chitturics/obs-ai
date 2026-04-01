---
 command: metasearch
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/metasearch
 title: metasearch
 download_date: 2026-02-03 09:11:36
---

 # metasearch

Retrieves event metadata from indexes based on terms in the <logical-expression>.

metasearch [<logical-expression>]

#### Optional arguments

#### Logical expression

#### Comparison expression

#### Index expression

#### Time options

The search allows many flexible options for searching based on time. For a list of time modifiers, see the topic Time modifiers for search in the Search Manual.

The metasearch command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

The metasearch command returns these fields:

| Field | Description |
| --- | --- |
| host | A default field that contains the host name or IP address of the network device that generated an event. |
| index | The repository for data. When the Splunk platform indexes raw data, it transforms the data into searchable events. |
| source | A default field that identifies the source of an event, that is, where the event originated. |
| sourcetype | A default field that identifies the data structure of an event. |
| splunk_server | The name of the instance where Splunk Enterprise is installed. |
| _time | The _time field contains an event's timestamp expressed in UNIX time. |

#### Example 1:

Return metadata on the default index for events with "404" and from host "webserver1".
 