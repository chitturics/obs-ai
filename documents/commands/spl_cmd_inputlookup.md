---
 command: inputlookup
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/inputlookup
 title: inputlookup
 download_date: 2026-02-03 09:09:44
---

 # inputlookup

Use the inputlookup command to search the contents of a lookup table. The lookup table can be a CSV lookup or a KV store lookup.

The required syntax is in bold.

#### Required arguments

You must specify either a <filename> or a <tablename>.

#### Optional arguments

The inputlookup command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.
The inputlookup command can be first command in a search or in a subsearch.

The lookup can be a file name that ends with .csv or .csv.gz, or a lookup table definition in Settings > Lookups > Lookup definitions.

#### Appending or replacing results

When using the inputlookup command in a subsearch, if append=true, data from the lookup file or KV store collection is appended to the search results from the main search. When append=false the main search results are replaced with the results from the lookup search.

#### Working with large CSV lookup tables

The WHERE clause allows you to narrow the scope of the query that inputlookup makes against the lookup table. It restricts inputlookup to a smaller number of lookup table rows, which can improve search efficiency when you are working with significantly large lookup tables.

#### Testing geometric lookup files

You can use the inputlookup command to verify that the geometric features on the map are correct. The syntax is | inputlookup <your_lookup>.

- For example, to verify that the geometric features in built-in geo_us_states lookup appear correctly on the choropleth map, run the following search:
| inputlookup geo_us_states
- On the Visualizations tab, zoom in to see the geometric features. In this example, the states in the United States.

#### Strict error handling

Use the strict argument to make inputlookup searches fail whenever they encounter an error condition. You can set this at the system level for all inputcsv and inputlookup searches by changing input_errors_fatal in limits.conf.

Note: If you use Splunk Cloud Platform, file a Support ticket to change the input_errors_fatal setting.

Use the strict argument to override the input_errors_fatal setting for an inputlookup search.

#### Additional information

For more information about creating lookups, see About lookups in the Knowledge Manager Manual.

For more information about the App Key Value store, see  About KV store in the Admin Manual.

#### 1. Read in a lookup table

Read in a usertogroup lookup table that is defined in the transforms.conf file.

#### 2. Append lookup table fields to the current search results

Using a subsearch, read in the usertogroup lookup table that is defined by a stanza in the transforms.conf file. Append the fields to the results in the main search.

#### 3. Read in a lookup table in a CSV file

Search the users.csv lookup file, which is in the  $SPLUNK_HOME/etc/system/lookups or $SPLUNK_HOME/etc/apps/<app_name>/lookups directory.

#### 4. Read in a lookup table from a KV store collection

Search the contents of the KV store collection kvstorecoll that have a CustID value greater than 500 and a CustName value that begins with the letter P. The collection is referenced in a lookup table called kvstorecoll_lookup. Provide a count of the events received from the table.

Note: In this example, the lookup definition explicitly defines the CustID field as a type of "number". If the field type is not explicitly defined, the where clause does not work. Defining field types is optional.

#### 5. View the internal key ID values for the KV store collection

Example 5: View internal key ID values for the KV store collection kvstorecoll, using the lookup table kvstorecoll_lookup. The internal key ID is a unique identifier for each record in the collection. This example uses the eval and table commands.

#### 6. Update field values for a single KV store collection record

Update field values for a single KV store collection record. This example uses the inputlookup, outputlookup, and eval commands. The record is indicated by the its internal key ID (the _key field) and this search updates the record with a new customer name and customer city. The record belongs to the KV store collection kvstorecoll, which is accessed through the lookup table kvstorecoll_lookup.

#### 7. Write the contents of a CSV file to a KV store collection

Write the contents of a CSV file to the KV store collection kvstorecoll using the lookup table kvstorecoll_lookup. The CSV file is in the $SPLUNK_HOME/etc/system/lookups or $SPLUNK_HOME/etc/apps/<app_name>/lookups directory.
 