---
 command: require
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/require
 title: require
 download_date: 2026-02-03 09:15:21
---

 # require

Causes a search to fail if the queries and commands that precede it in the search string do not return any events or results.

The required syntax is in bold.

When require is used in a search string, it causes the search to fail if the queries and commands that precede it in the search string return zero events or results. When you use it in a subsearch, it causes the parent search to fail when the subsearch fails to return results.

Use this command to prevent the Splunk platform from running zero-result searches when this might have certain negative side effects, such as generating false positives, running custom search commands that make costly API calls, or creating empty search filters via a subsearch.

The require command cannot be used in real-time searches.

#### Require and subsequent commands

Do not expect the require command to mitigate all possible negative consequences of a search. When the require command causes a search to fail, it prevents subsequent commands in the search from receiving the results, but it does not prevent the Splunk software from invoking those commands before the search is finalized. This means that those subsequent search command processors may receive empty "chunks" before the search is finalized.

If you are implementing a custom search command, make sure it interoperates well with the require command. Ensure that it avoids exhibiting side effects in response to partial input.

See Create custom search commands for apps in Splunk Cloud Platform or Splunk Enterprise  in the Developer Guide on the Developer Portal.

#### 1. Cause a search to fail if it doesn't return any results or events

If a search doesn't return any results, the require command causes the search to fail.

#### 2. Raise an exception if the subsearch returns zero events or results, and stop the parent search.
 