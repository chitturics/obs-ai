---
 command: localize
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/localize
 title: localize
 download_date: 2026-02-03 09:10:34
---

 # localize

The localize command generates results that represent a list of time contiguous event regions. An event region is a period of time in which consecutive events are separated, at most, by the maxpause time value. The regions found can be expanded using the timeafter and timebefore arguments.

The regions discovered by the localize command are meant to be fed into the map command. The map command uses a different region for each iteration.

localize [<maxpause>] [<timeafter>] [<timebefore>]

#### Optional arguments

#### Expanding event ranges

You can expand the event range after the last event or before the first event in the region. These expansions are done arbitrarily, possibly causing overlaps in the regions if the values are larger than maxpause.

#### Event region order

The regions are returned in search order, or descending time for historical searches and data-arrival order for realtime search. The time of each region is the initial pre-expanded start-time.

#### Other information returned by the localize command

The localize command also reports:

- The number of events in the range
- The range duration in seconds
- The region density defined as the number of events in range divided by <range duration - events per second.

#### 1. Search the time range of each previous result for the term "failure"

#### 2: Finds suitable regions around where "error" occurs

Searching for "error" and calling the localize command finds suitable regions around where error occurs and passes each on to the search inside of the map command. Each iteration works with a specific time range to find potential transactions.

map, transaction
 