---
 command: tags
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tags
 title: tags
 download_date: 2026-02-03 09:18:48
---

 # tags

Annotates specified fields in your search results with tags. If there are fields specified, only annotates tags for those fields. Otherwise, this command looks for tags for all fields. See About tags and aliases in the Knowledge Manager Manual.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The tags command is a distributable streaming command. See Command types.

#### Viewing tag information

To view the tags in a table format, use a command before the tags command such as the stats command.  Otherwise, the fields output from the tags command appear in the list of Interesting fields. See Examples.

#### Using the <outputfield> argument

If outputfield is specified, the tag names for the fields are written to this field. By default, the tag names are written in the format <field>::<tag_name>. For example, sourcetype::apache.

If outputfield is specified, the inclname and inclvalue arguments control whether or not the field name and field values are added to the outputfield. If both inclname and inclvalue are set to true, then the format is <field>::<value>::<tag_name>. For example, sourcetype::access_combined_wcookie::apache.

#### 1. Results using the default settings

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

This search looks for web access events and counts those events by host.

| host | count |
| --- | --- |
| www1 | 13628 |
| www2 | 12912 |
| www3 | 12992 |

When you use the tags command without any arguments, two new fields are added to the results tag and tag::host.

| host | count | tag | tag::host |
| --- | --- | --- | --- |
| www1 | 13628 | tag2 | tag2 |
| www2 | 12912 | tag1 | tag1 |
| www3 | 12992 |  |  |

There are no tags for host=www3.

```
sourcetype
```

```
stats
```

| host | sourcetype | count | tag | tag:host | tag::sourcetype |
| --- | --- | --- | --- | --- | --- |
| www1 | access_combined_wcookie | 13628 | apache
tag2 | tag2 | apache |
| www2 | access_combined_wcookie | 12912 | apache
tag1 | tag1 | apache |
| www3 | access_combined_wcookie | 12992 | apache |  | apache |

The tag field list all of the tags used in the events that contain the combination of host and sourcetype.

The tag::host field list all of the tags used in the events that contain that host value.

The tag::sourcetype field list all of the tags used in the events that contain that sourcetype value.

#### 2. Specifying a list of fields

Return the tags for the host and eventtype fields.

#### 3. Specifying an output field

Write the tags for all fields to the new field test.

The results look like this:

| host | sourcetype | count | test |
| --- | --- | --- | --- |
| www1 | access_combined_wcookie | 13628 | apache
tag2 |
| www2 | access_combined_wcookie | 12912 | apache
tag1 |
| www3 | access_combined_wcookie | 12992 | apache |

#### 4. Including the field names in the search results

Write the tags for the host and sourcetype fields into the test field. New fields are returned in the output using the format host::<tag> or sourcetype::<tag>. Include the field name in the output.

The results look like this:

| host | sourcetype | count | test |
| --- | --- | --- | --- |
| www1 | access_combined_wcookie | 13628 | sourcetype::apache
host::tag2 |
| www2 | access_combined_wcookie | 12912 | sourcetype::apache
host::tag1 |
| www3 | access_combined_wcookie | 12992 | sourcetype::apache |

#### 5. Identifying a specific a list of tags to return

Write the "error" and "group" tags for the host field into the test field. New fields are returned in the output using the format host::<tag>. Include the field name in the output.

If you don't have a command before the tags command that organizes the results in a table format, you will see the output of the tags command in the Interesting fields list, as shown in the following image:

Notice that the tag field in the list of Interesting fields shows that there are 3 tag values. Because the search specified that only the error and group tags should be returned to the test output field, those are the only tag values that appear in the image.
 