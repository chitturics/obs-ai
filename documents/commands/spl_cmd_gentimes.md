---
 command: gentimes
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/gentimes
 title: gentimes
 download_date: 2026-02-03 09:08:33
---

 # gentimes

The gentimes command is useful in conjunction with the map command.

Generates timestamp results starting with the exact time specified as start time. Each result describes an adjacent, non-overlapping time range as indicated by the increment value. This terminates when enough results are generated to pass the endtime value.

The gentimes command generates events up to the end time, but not including the end time.

| gentimes start=<timestamp> [end=<timestamp>] [increment=<increment>]

#### Required arguments

#### Optional arguments

The gentimes command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

The gentimes command returns four fields.

| Field | Description |
| --- | --- |
| starttime | The starting time range in UNIX time. |
| starthuman | The human readable time range in the format DDD MMM DD HH:MM:SS YYYY. For example Sun Apr 4 00:00:00 2021. |
| endtime | The ending time range in UNIX time. |
| endhuman | The human readable time range in the format DDD MMM DD HH:MM:SS YYYY. For example Fri Apr 16 23:59:59 2021. |

To specify future dates, you must include the end argument.

#### 1. Generate daily time ranges by specifying dates

Generates daily time ranges from April 4 to April 7 in 2021. This search generates events up to the end time, but not including the end time. This search generates three intervals covering one day periods aligning with the calendar days April 4, 5, and 6, during 2021. The gentimes command generates events up to the end time, but not including the end time.

The results look like this:

| endhuman | endtime | starthuman | starttime |
| --- | --- | --- | --- |
| Sun Apr 4 23:59:59 2021 | 1617605999 | Sun Apr 4 00:00:00 2021 | 1617519600 |
| Mon Apr 5 23:59:59 2021 | 1617692399 | Mon Apr 5 00:00:00 2021 | 1617606000 |
| Tue Apr 6 23:59:59 2021 | 1617778799 | Tue Apr 6 00:00:00 2021 | 1617692400 |

#### 2. Generate daily time ranges by specifying relative times

Generate daily time ranges from 30 days ago until 27 days ago.

#### 3. Generate hourly time ranges

Generate hourly time ranges from December 1 to December 5 in 2021.

#### 4. Generate time ranges by only specifying a start date

Generate daily time ranges from April 25 to today.

#### 5. Generate weekly time ranges

Although the week increment is not supported, you can generate a weekly increment by specifying increment=7d.

This examples generates weekly time ranges from December 1, 2021 to April 30, 2022.
 