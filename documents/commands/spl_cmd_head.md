---
 command: head
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/head
 title: head
 download_date: 2026-02-03 09:08:57
---

 # head

Returns the first N number of specified results in search order. This means the most recent N events for a historical search, or the first N captured events for a real-time search. The search results are limited to the first results in search order.

There are two types of limits that can be applied: an absolute number of results, or an expression where all results are returned until the expression becomes false.

The required syntax is in bold.

#### Required arguments

If no options or limits are specified, the head command returns the first 10 results.

#### Optional arguments

The head command is a centralized streaming command. See Command types.

#### Setting limits

If a numeric limit such as a numeric literal or the argument limit=<int> is used, the head command returns the first N results where N is the selected number.  Using both the numeric limit and limit=<int> results in an error.

#### Using an <eval-expression>

If an <eval-expression> is used, all initial results are returned until the first result where the expression evaluates to false.  The result where the <eval-expression> evaluates to false is kept or dropped based on the keeplast argument.

If both a numeric limit and an <eval-expression> are used, the smaller of the two constraints applies. For example, the following search returns up to the first 10 results, because the <eval-expression> is always true.

However, this search returns no results because the <eval-expression> is always false.

#### 1. Return a specific number of results

Return the first 20 results.

#### 2. Return results based on a specified limit

Return events until the time span of the data is >= 100 seconds

... | streamstats range(_time) as timerange | head (timerange<100)

#### 1. Using the keeplast and null arguments

The following example shows the search results when an <eval-expression> evaluates to NULL,  and the impact of the  keeplast and null arguments on those results.

Let's start with creating a set of events. The eval command replaces the value 3 with NULL in the count field.

| makeresults count=7
| streamstats count 
| eval count=if(count=3,null(), count)

The results look something like this:

| _time | count |
| --- | --- |
| 2020-05-18 12:46:51 | 1 |
| 2020-05-18 12:46:51 | 2 |
| 2020-05-18 12:46:51 |  |
| 2020-05-18 12:46:51 | 4 |
| 2020-05-18 12:46:51 | 5 |
| 2020-05-18 12:46:51 | 6 |
| 2020-05-18 12:46:51 | 7 |

When null is set to true, the head command continues to process the results. In this example the command processes the results, ignoring NULL values, as long as the count is less than 5. Because keeplast=true the event that stopped the processing, count 5, is also included in the output.

| makeresults count=7
| streamstats count 
| eval count=if(count=3,null(), count) 
| head count<5 keeplast=true null=true

| _time | count |
| --- | --- |
| 2020-05-18 12:46:51 | 1 |
| 2020-05-18 12:46:51 | 2 |
| 2020-05-18 12:46:51 |  |
| 2020-05-18 12:46:51 | 4 |
| 2020-05-18 12:46:51 | 5 |

When null is set to false, the head command stops processing the results when it encounters a NULL value. The events with count 1 and 2 are returned. Because  keeplast=true the event with the NULL value that stopped the processing, the third event, is also included in the output.

| makeresults count=7 
| streamstats count 
| eval count=if(count=3,null(), count) 
| head count<5 keeplast=true null=false

| _time | count |
| --- | --- |
| 2020-05-18 12:46:51 | 1 |
| 2020-05-18 12:46:51 | 2 |
| 2020-05-18 12:46:51 |  |
 