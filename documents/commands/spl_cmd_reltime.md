---
 command: reltime
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/reltime
 title: reltime
 download_date: 2026-02-03 09:15:03
---

 # reltime

Creates one or more relative time fields and adds the field or fields to returned events. Each added relative time field provides a human-readable value of the difference between "now" (the start time of the search) and the timestamp value of a corresponding field in the returned event. Human-readable values look like 5 days ago, 1 minute ago, 2 years ago, and so on.

The required syntax is in bold.

#### Optional arguments

The reltime command adds one or more relative time fields to your events. Each field added provides a human-readable value that represents the difference between now (the start time of the search) and the timestamp value of a field in the event.

For example, say you tie reltime to the _time fields in your events. If you run a search at 6 a.m., and the search returns an event with a _time value that translates to 5 a.m., reltime adds a field to that event named reltime with the value 1 hour ago.

If you use reltime without arguments, the command adds a relative time field to your events named reltime. This new field will be based on the _time field in each of your events.

The following table explains how reltime defines and names the fields that it adds.

| Custom timefield specified? | Custom prefix specified? | Basis for field(s) added by reltime | Name(s) of field(s) added by reltime |
| --- | --- | --- | --- |
| None | No | _time | reltime |
| One timefield specified | No | The time field you specified for timefield | reltime |
| One timefield specified | Yes | The time field you specified for timefield | reltime, prefixed by your custom prefix string |
| Multiple time fields specified | No | The list of time fields you specified for  timefield | The names of the fields you specified for timefield, prefixed by reltime_ |
| Multiple time fields specified | Yes | The list of time fields you specified for  timefield | The names of the fields you specified for timefield, prefixed by your custom prefix string |

The reltime command is a distributable streaming command. See Command types.

#### Example 1:

Adds a field called reltime to the events returned by the search, based on the _time field in those events.

#### Example 2:

Adds a field called reltime to events returned by the search, based on the earliest_time field in those events.

#### Example 3:

Adds a field called reltime_now_current_time to events, based on the current_time field in those events.

#### Example 4:

Adds three new relative time fields called reltime_max_time, reltime_min_time, and reltime_current_time to returned events with max_time, min_time, and current_time fields.

#### Example 5:

Adds two new relative time fields called usr_prefix_max_time and usr_prefix_min_time to returned events with max_time and min_time fields.
 