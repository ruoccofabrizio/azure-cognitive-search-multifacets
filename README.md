# Azure Cognitive Search - Multifacets

This repo implements a client-side facets management to deal with multi-selection faceting using Azure Cognitive Search.

It relies on a combination of queries to Azure Cognitive Search and results set stored locally in a session store.


## Main function
The "main" function defines some variables to be stored in a session store:
-   filters: list of all the filters applied in the UI (facet names, facet values and facet counter as shown to the users)
-   local_query: local store of the results set retrived by querying Azure Cognitive Search
-   send_new_query: boolean variable to evaluate the need to send a new query to Azure Cognitive Search or compute the results set and the facets locally
-   exclude: list of field facets that have to be computed remotely on Azure Cognitive Search instead of using the locally stored results set

```python
# MAIN 
try:
    # Create a Session variable collecting applied filters
    if "filters" not in st.session_state:
        st.session_state['filters'] = []  
    # Create a Session variable to use local data when the query does not change
    if "local_query" not in st.session_state:
        st.session_state['local_query'] = {
            "query": "",
            "results": {}
        }
    # Create a Session variable to control when to submit a new query to Azure Cognitive Search
    if "send_new_query" not in st.session_state:
        st.session_state['send_new_query'] = True
    # Create a Session variable to store facets that have to be compute on Azure Cognitive Search
    if "exclude" not in st.session_state:
        st.session_state['exclude'] = []
```

After setting the session variables, the "main" function calls the "send_query" function, using the terms retrieved from the search bar.
Finally, all the facets defined in the application settings are added to the UI with the "add_facet" function.
```python
    # Send Query to Azure Cognitive Search
    r = send_query(search=search)
    # Add facets for configured fields
    for f in os.environ['facets'].replace(' ','').split(','):
        add_facet(f)
```

## add_facet
The _add_facet_ function pushes in the UI all the facet values and computes the counters as well.

It retrieves a facets list from the latest available results set:
```python
    # Read facet value from the last query if available
    facet_values = []
    if r.get('@search.facets') != None and r.get('@search.facets').get(facet) != None:
        facet_values = r.get('@search.facets').get(facet)
```

Then check for filters that have been selected in the UI and stores them in the active_filters list:
 
```python
    # Extract all the filter already active in the UI for rendering them as selected
    active_filters = list(filter(None,map(lambda x: x['value'] if x['facet'] == facet else None, st.session_state['filters'])))
    active_filters = active_filters[0] if len(active_filters) > 0 else []
```

Finally, for each facet it adds a checkbox to the UI with the value "selected" (True) if the facet was already selected, "unselected" (False) otherwise.
The function also defines a call-back function to "push_filter" to manage the click on the specific checkbox in the UI, passing as a parameter a concatenated string of the facet name, facet value and facet count.
```python
    # Draw all the facet buttons in the UI and define the callback function
    for f in facet_values:
        st.sidebar.checkbox(f['value'] + ' (' + str(f['count']) +')' ,
            on_change=push_filter, 
            value= True if f['value'] in active_filters else False,
            kwargs={"checkbox_key" : f"facet${facet}${f['value']}#{f['count']}"}
            )
```

## push_filter
The _push_filter_ function is called directly by the UI when the user selects or de-selects a filter in the facets menu.

Initially it splits the different information passed as parameters to extract:
-   facet name
-   facet value
-   facet count
```python
    # Get facet and value from filter
    facet = checkbox_key.split('$')[1]
    value = checkbox_key.split('$')[2].split('#')[0]
    count = checkbox_key.split('$')[2].split('#')[1]
```

Then it checks if the selected facet name is already present in the filters to add the facet value to the current filter or remove it if the value is already present (in this case the user is de-selecting the filter in the UI, instead of selecting it). 

Finally if the specified facet is part of the exclude list (the list that qualifies a facet for remote compute on Azure Cognitive Search, instead of local computing), set the send_new_query session variable to True as a new query to Azure Cognitive Search is required.
```python
    # if facet is not in active filters add the filter
    if facet not in list(map(lambda x: x['facet'], st.session_state['filters'])):
        st.session_state['filters'].append({"facet": facet, "value": [value], "count": int(count)})
    else:
        # if the facet is already in the active filter, retrieve the item in the filter list
        filt = list(filter(lambda x: x['facet'] == facet, st.session_state['filters']))[0]
        # if the value for the facet is already in the active filters, remove it (this happens when in the UI you deselect the filter)
        if value in filt['value']:
            filt['value'].remove(value)
            # if all the values for the specific facet are removed, remove the filter as well from the active filters
            if filt['value'] == []:
                st.session_state['filters'] = list(filter(lambda x: x['facet'] != facet, st.session_state['filters']))
        # if the value is not in the active filters list, add it
        else:
            filt['value'].append(value)
            filt['count'] += int(count)
            # if the facet is in the list for remotely computes on Azure Cognitive Search, throw a new query to get a new result set
            if filt['facet'] in st.session_state['exclude']:
                # print('NEED TO SEND A NEW QUERY')
                st.session_state['send_new_query'] = True
                st.session_state['exclude'] = [filt['facet']]
```


## send_query
The _send_query_ function implements the core logic for calling the Azure Cognitive Search service and managing the local results set, according to specific conditions that may happen during the page navigation.

The first conditional branch checks the following criterias to evaluate if a new query has to be submitted to Azure Cognitive Search or the results set and the facets should be managed locally, using the session storage:

A new query to Azure Cognitive Search is required when:
-   the search terms saved in the session store are different from the search terms currently typed in the UI
-   OR the previous search results dataset has more documents than the selected documents stored locally
-   OR an explicit need for new query to Azure Cognitive Search


```python
    # Evalute if you need to issue a new query to Search Engine or work with session data 
    # Here you can also add considerations on the number of items in the result to issue other queries for faceting if needed
    if st.session_state['local_query']['query'] != search or st.session_state['local_query']['results']['@odata.count'] > top or st.session_state['send_new_query']:
```

When any of the previous conditions is met:
-   The search terms are stored in the local session store
-   IF the docs count of the query is greater than results count stored locally OR there is an explicit request for a new query to be submitted
    THEN apply a dynamic boost to specified filters to push on top of the results set all the items matching the filters, while still keeping others as part of the results for computing the facets remotely on Azure Cognitive Search
-   A new query is sent to Azure Cognitive Search
-   Update the local result set with data retrieved from Azure Cognitive Search
-   Use the previous result set to compute the facets locally for all the fields but the ones that exceed the local results set count (which have been computed remotely as part of the query to Azure Cognitive Search)


```python
        # Store the search query in the Session Store
        st.session_state['local_query']['query'] = search

        # Create the full query with boosting of selected facets 
        # ONLY needed when your results set is over 1K (or defined tops) docs
        full_search = f"({search})"
        # if a new query has to be submitted, reset the exclusion for local facet computing
        st.session_state['exclude'] = [] if not st.session_state['send_new_query'] else st.session_state['exclude'] 
        # if locally stored result set has more items than 1K (or defined tops) docs, create a dynamic boost to push on top the item with selected facet
        if st.session_state['local_query'].get('results') != None:
            if st.session_state['local_query']['results'].get('@odata.count', 0) > top or st.session_state['send_new_query']:
                # print(f"filters: {st.session_state['filters']}")
                for f in st.session_state['filters']:
                    if not st.session_state['send_new_query']:
                        st.session_state['exclude'].append(f['facet'])
                    search_filters = " OR ".join(list(map(lambda x: f"{f['facet']}:{x}^1000", f['value'])))
                    full_search += f" ({search} AND ({search_filters}))" 

        # Create the request body
        body = {
            "search" : full_search,
            "facets" : facets,
            "queryType" : "full",
            "count" : True,
            "top": top
        }
        # Log request body for debugging
        pprint(body)
        # Send request to Azure Cognitive Search
        r = requests.post(url, headers=headers, json=body)
        # Log request status code
        print(r.status_code)
        # Print an error if request fails
        if not r.ok:
            r.text

        # Update Session results with data coming from Azure Cognitive Search
        res = r.json()
        previous = copy(st.session_state['local_query']['results'])
        st.session_state['local_query']['results'] = res

        if previous != {}: #if results are already in the session
            # compute facets locally for all the fields but the excluded (as not part of the local result set)
            res['@search.facets'] = compute_facets(st.session_state['exclude'])

            # filter the new result set to remove all the items not selected by the filter
            for f in st.session_state['filters']:
                res['value'] = list(filter(lambda x: x[f['facet']] in f['value'], res['value']))
            # Count the results locally and override the service data
            res['value'] = st.session_state['local_query']['results']['value']
            res['@odata.count'] = len(st.session_state['local_query']['results']['value'])

        # Set new query to false as the results set is saved locally for further filtering
        st.session_state['send_new_query'] = False
```


When those conditions are not met, the code can compute the facet locally as the full results set is available in the session store:
-   Locally filter the results set using the session variable "filters" updated directly by the clicks on the UI
-   Assign the locally computed results set to the same structure as for remote results set
-   Update the facets for all the fields
-   Update the results set len by re-computing it locally
```python
    else:
        print("Local facetings")
        res = copy(st.session_state['local_query']['results'])        
        results = copy(st.session_state['local_query']['results'])['value']
        
        # Apply active filters on the result set
        for f in st.session_state['filters']:
            results = list(filter(lambda x: x[f['facet']] in f['value'], results))

        # Overwrite new results, facets and result lenght for visualization
        res['value'] = results
        res['@search.facets'] = compute_facets(st.session_state['exclude'])
        res['@odata.count'] = len(results)
        
    return res
```


## compute_facets - Locally compute the facets
The _compute_facets_ function locally computes facets on a saved results set in the session store. Some fields can be excluded from facet computation for specific conditions using the exclude parameter. 
These facets are remotely computed by sending a single query to Azure Cognitive Search.

```python 
# Locally compute the search facets
def compute_facets(exclude=[]):
    search_facets = {}
    search_facets_output = {}
    facets = os.environ['facets'].replace(' ','').split(',')
    # check if any facet has to be compute on server side
    if len(exclude) > 0:
        print("Getting remote facet")
        remote_facets_output = query_facets(search, exclude)
    # For each facet count the docs applying all filters but those on the facet itself, starting from the full result set
    for facet in facets:
        if facet not in exclude:
            search_facets[facet] = copy(st.session_state['local_query']['results'])['value']
            for f in st.session_state['filters']:
                if f['facet'] != facet: # Exclude the filter on the facet you are computing the counter
                    search_facets[facet] = list(filter(lambda x: x[f['facet']] in f['value'] , search_facets[facet]))
            # Count all the values and re-format in the ['@search.facets'] format
            search_facets_output[facet] = []
            for k,v in Counter(list(map(lambda x: x[facet], search_facets[facet]))).items():
                search_facets_output[facet].append({"count": v, "value": k})
            search_facets_output[facet] = sorted(search_facets_output[facet], key= lambda x: x['count'], reverse=True)
        else:
            search_facets_output[facet] = remote_facets_output[facet]
    return search_facets_output
```

## query_facets - Remote compute the facets
The _query_facet_ function computes facets remotely on Azure Cognitive Search using the session variable "filters" to cut the results set accordingly to facet selections in the UI.

```python
def query_facets(search, exclude):
    print("Query for facets")
    url = f"https://{os.environ['search_service']}.search.windows.net/indexes/{os.environ['index_name']}/docs/search?api-version={os.environ['api_version']}"
    # Required authentication headers
    headers = {
        "content-type" : "application/json",
        "api-key" : os.getenv('api_key')
    }
    # Compute facet with Azure Cognitive Search format
    facets = {x : f"{x},count:50" for x in exclude}#.replace(' ','').split(',')}
    facets = [v for k,v in facets.items()]

    # Create filter for facet retrieval on Azure Cognitive Search
    odata_filter = ""
    for f in st.session_state['filters']:
        if f['facet'] not in exclude:#replace(' ','').split(','):
            filter_values = ",".join(list(map(lambda x: f"{x}", f['value'])))
            odata_filter += ' and ' if odata_filter != "" else ''
            odata_filter += f"search.in({f['facet']}, '{filter_values}')"

    # print(odata_filter)

    # Create the request body
    body = {
        "search" : search,
        "facets" : facets,
        "queryType" : "full",
        "count" : True,
        "top": top,
        "select": 'id',
        "filter" : odata_filter
    }

    # Log request body for debugging
    pprint(body)
    # Send request to Azure Cognitive Search
    r = requests.post(url, headers=headers, json=body)
    # Log request status code
    print(r.status_code)
    # Print an error if request fails
    if not r.ok:
        r.text

    return r.json()['@search.facets']
```