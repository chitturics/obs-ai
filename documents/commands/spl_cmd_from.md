---
 command: from
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/from
 title: from
 download_date: 2026-02-03 09:08:14
---

 # from

The from command retrieves data from a dataset, such as a data model dataset, a CSV lookup, a KV Store lookup, a saved search, or a table dataset.

Design a search that uses the from command to reference a dataset. Optionally add additional SPL such as lookups, eval expressions, and transforming commands to the search. Save the result as a report, alert, or dashboard panel. If you use Splunk Cloud Platform, or use Splunk Enterprise and have installed the Splunk Datasets Add-on, you can also save the search as a table dataset.

See the Usage section.

The required syntax is in bold.

You can specify a colon ( : ) or a space between <dataset_type> and  <dataset_name>.

#### Required arguments

Note: In older versions of the Splunk software, the term "data model object" was used.  That term has been replaced with "data model dataset".

#### Optional arguments

The from command is a generating command. It can be either report-generating or event-generating depending on the search or knowledge object that is referenced by the command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search. However, you can use the from command inside the append command.

When you use the from command, you must reference an existing dataset. You can reference any dataset listed in the Datasets listing page, such as data model datasets, CSV lookup files, CSV lookup definitions, and table datasets. You can also reference saved searches and KV Store lookup definitions. See View and manage datasets in the Knowledge Manager Manual.

#### Knowledge object dependencies

When you create a knowledge object such as a report, alert, dashboard panel, or table dataset, that knowledge object has a dependency on the referenced dataset. This is referred to as a dataset extension. When you make a change to the original dataset, such as removing or adding fields, that change propagates down to the reports, alerts, dashboard panels, and tables that have been extended from that original dataset. See Dataset extension in the Knowledge Manager Manual.

#### When field filtering is disabled for a data model

When you search the contents of a data model using the from command, by default the search returns a strictly-filtered set of fields. It returns only default fields and fields that are explicitly identified in the constraint search that defines the data model.

If you have edit access to your local datamodel.conf file, you can disable field filtering for specific data models by adding the  strict_fields=false setting to their stanzas. When you do this, | from searches of data models with that setting return all fields related to the data model, including fields inherited from parent data models, fields extracted at search time, calculated fields, and fields derived from lookups.

#### 1. Search a data model

Search a data model that contains internal server log events for REST API calls.  In this example, internal_server is the data model name and splunkdaccess is the dataset inside the internal_server data model.

#### 2. Search a lookup file

Search a lookup file that contains geographic attributes for each country, such as continent, two-letter ISO code, and subregion.

#### 3. Retrieve data by using a lookup file

Search the contents of the KV store collection kvstorecoll that have a CustID value greater than 500 and a CustName value that begins with the letter P. The collection is referenced in a lookup table called kvstorecoll_lookup.  Using the stats command, provide a count of the events received from the table.

#### 4. Retrieve data using a saved search

This search retrieves the timestamp and client IP from the saved search called mysecurityquery.

| from savedsearch:mysecurityquery | fields _time clientip ...

The search results look something like this.

Even if the saved search is scheduled, this search is rerun, which can be expensive and lead to concurrency issues if more searches are run at the same time than the system can support. Alternatively, you can use the loadjob command instead of the from command in conjunction with a scheduled search if you are concerned about the number and frequency of searches that your users run.

#### 5. Specify a dataset name that contains spaces

When the name of a dataset includes spaces, enclose the dataset name in quotation marks.
 