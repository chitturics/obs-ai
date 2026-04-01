---
 command: typeahead
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/typeahead
 title: typeahead
 download_date: 2026-02-03 09:20:22
---

 # typeahead

Returns autosuggest information for a specified prefix that is used to autocomplete word candidates in searches. The maximum number of results returned is based on the value you specify for the  count argument.

Note: Certain restricted search commands, including mpreview, mstats, tstats, typeahead, and walklex, might stop working if your organization uses field filters to protect sensitive data. See Plan for field filters in your organization in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The typeahead command is a generating command and should be the first command in the search. Generating commands use a leading pipe character.

The typeahead command can be targeted to an index and restricted by time.

When you run the typeahead command, Splunk software runs internal typeahead searches and extracts data from indexes, configurations, and search histories. This information is used to autocomplete word candidates when users type commands in the Search bar in Splunk Web. The typeahead command extracts data from these sources:

- Terms or tokens from the index lexicon.
- Settings in configuration files, such as props.conf and savedsearches.conf.
- The search history from previous searches in Splunk Web.

#### Protect sensitive information in typeahead searches

If you have sensitive information, such as Personal Identifiable Information (PII) and Protected Health Information (PHI) data that you don't want to be visible to users when they run typeahead searches, you can use the banned_segments argument to prevent sensitive data from displaying in typeahead searches.

For example, to make sure that password or social security information is not visible to users, you can add a new line for the banned_segments setting to the typeahead stanza in the limits.conf file like this:

Then, when your users run typeahead searches, any fields containing password, SSN, or ssn are filtered from the search results.

#### Splunk Cloud Platform

#### Splunk Enterprise

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- In the typeahead stanza, set banned_segments to the string that you want filtered out as the prefix in typeahead searches.

#### The impact of typeahead on search results

The typeahead command returns the most common terms found in indexed data with the given prefix. If you use the typeahead command with the default settings, the command may not return all search results or the correct search results in the following cases:

- The time to complete the search takes longer than the value specified by the max_time argument, which is 1 second, by default.
- Data is indexed on a server that is not randomly chosen, resulting in the exclusion of its data from the search results. This can happen when the value of max_server is less than the number of indexers, for example, if max_server is set to the default, which is 2, but there are actually 3 indexers.

In addition, the typeahead command may not return all of the search results if the count argument is set lower than the actual number of results. For example, if the count argument is set to 10, the typeahead command returns only the top 10 results, even though more results could actually be returned.

#### Set the number of additional search peers used in a typeahead job

The max_servers argument is designed to minimize the workload impact of running typeahead search jobs in an indexer clustering environment. For load balancing, the selection of additional search peers for typeahead is random.

A setting of 0 removes all limits, causing all available search peers to be used for typeahead search jobs.

The default for the max_servers argument is controlled by the max_servers setting in limits.conf.

#### Typeahead and .conf file updates

The typeahead command uses a cache to run fast searches at the expense of accurate results. As a result, sometimes what is in the cache and shows up in typeahead search results may not reflect recent changes to .conf files. This is because it takes 5 or 10 minutes for the cached data to clear, depending on the performance of the server. For example, if you rename a sourcetype in the props.conf file, it may take a few minutes for that change to display in typeahead search results. A typeahead search that is run while the cache is being cleared returns the cached data, which is expected behavior.

If you make a change to a .conf file, you can wait a few minutes for the cache to clear to get the most accurate and up-to-date results from your typeahead search. Alternatively, you can turn off the use_cache argument to clear the cache immediately, which fetches more accurate results, but is a little slower. After you manually clear the cache, you should see the changes to your .conf file reflected in your results when you rerun the typeahead search.

For more information, see Rename source types in the Splunk Cloud Platform Getting Data In manual.

#### Typeahead and tsidx bucket reduction

typeahead searches over indexes that have undergone tsidx bucket reduction will return incorrect results.

For more information see Reduce tsidx disk usage in Managing indexers and clusters of indexers.

#### Example 1: Return typeahead information for source

When you run a typeahead search, Splunk software extracts information about field definitions from indexes, configurations, and search histories, and displays the relevant information for the specified prefix. For example, say you run the following search for the source prefix against the main index:

The typeahead command searches the index and shows you what is visible to your users as autocomplete suggestions when they start to type source in their searches in Splunk Web. The results look something like this:

| content | count | operator |
| --- | --- | --- |
| source="access_30DAY.log" | 131645 | false |
| source="data.csv" | 4 | false |
| source="db_audit_30DAY.csv" | 44096 | false |

#### Example 2: Return typeahead information for saved searches

You can also run typeahead on saved searches. For example, say you run this search:

The results look something like this, which tells you what your users see as autocomplete suggestions when they start to type savedsearch in the Search bar in Splunk Web.

| content | count | operator |
| --- | --- | --- |
| savedsearch="403_by_clientip" | 26 | true |
| savedsearch="Errors in the last 24 hours" | 5 | true |
| savedsearch="Errors in the last hour" | 2 | true |

#### Example 3: Return typeahead information for sourcetypes in the _internal index

When you run the following typeahead search, Splunk software returns typeahead information for sourcetypes in the _internal index.

The results look something like this.

| content | count | operator |
| --- | --- | --- |
| sourcetype | 373993 | false |
| sourcetype="mongod" | 711 | false |
| sourcetype="scheduler" | 2508 | false |
| sourcetype="splunk_btool" | 3 | false |
| sourcetype="splunk_intro_disk_objects" | 5 | false |
 