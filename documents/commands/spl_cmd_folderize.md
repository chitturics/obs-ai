---
 command: folderize
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/folderize
 title: folderize
 download_date: 2026-02-03 09:07:46
---

 # folderize

Creates a higher-level grouping, such as replacing filenames with directories. Replaces the attr attribute value with a more generic value, which is the result of grouping the attr value with other values from other results, where grouping occurs by tokenizing the attr value on the sep separator value.

For example, the folderize command can group search results, such as those used on the Splunk Web home page, to list hierarchical buckets (e.g. directories or categories). Rather than listing 200 sources, the folderize command breaks the source strings by a separator (e.g. /) and determines if looking only at directories results in the number of results requested.

folderize attr=<string> [sep=<string>] [size=<string>] [minfolders=<int>] [maxfolders=<int>]

#### Arguments

#### 1. Group results into folders based on URI

Consider this search.

The following image shows the results of the search run using the All Time time range. Many of the results start with /en-US/account. Because some of the URIs are very long, the image does not show the second column on the far right. That column is the count(uri) column created by the stats command.

Using the folderize command, you can summarize the URI values into more manageable groupings.

The following image shows the URIs grouped in the result set.

In this example, the count(uri) column is the count of the unique URIs that were returned from the stats command. The
memberCount column shows the count of the URIs in each group.  For example, the /en-US/ URI was found 22 times in the events, as shown in the count(uri) column. When the folderize command arranges the URI into groups, there is only 1 member in the /en-US/ group.  Whereas the URIs that start with /services/ occurred 10088 times in the events, but there are only 1648 unique members in the /services/* group.
 