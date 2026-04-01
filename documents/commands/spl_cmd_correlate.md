---
 command: correlate
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/correlate
 title: correlate
 download_date: 2026-02-03 09:04:04
---

 # correlate

Calculates the correlation between different fields.

You can use the correlate command to see an overview of the co-occurrence between fields in your data. The results are presented in a matrix format, where the cross tabulation of two fields is a cell value. The cell value represents the percentage of times that the two fields exist in the same events.

The field the result is specific to is named in the value of the RowField field, while the fields it is compared against are the names of the other fields.

There is a limit on the number of fields that correlate considers in a search.
From limits.conf, stanza [correlate], the maxfields sets this ceiling. The default is 1000.

If more than this many fields are encountered, the correlate command continues to process data for the first N (eg thousand) field names encountered, but ignores data for additional fields. If this occurs, the notification from the search or alert contains a message "correlate: input fields limit (N) reached.  Some fields may have been ignored."

As with all designed-in limits, adjusting this might have significant memory or cpu costs.

#### Example 1:

Look at the co-occurrence between all fields in the _internal index.

Here is a snapshot of the results.

Because there are different types of logs in the _internal, you can expect to see that many of the fields do not co-occur.

#### Example 2:

Calculate the co-occurrences between all fields in Web access events.

You expect all Web access events to share the same fields: clientip, referer, method, and so on. But, because the sourcetype=access_* includes both access_common and access_combined Apache log formats, you should see that the percentages of some of the fields are less than 1.0.

#### Example 3:

Calculate the co-occurrences between all the fields in download events.

The more narrow your search is before you pass the results into correlate, the more likely it is that all the field value pairs have a correlation of 1.0. A correlation of 1.0 means the values co-occur in 100% of the search results. For these download events, you might be able to spot an issue depending on which pairs have less than 1.0 co-occurrence.

associate, contingency
 