import React, {useEffect}  from 'react';
import { gql, useQuery, useMutation, useLazyQuery } from '@apollo/client';
import { useReactiveVar } from '@apollo/client';
import { meState } from '../../../cache';
import {BrowserScriptsTable} from './BrowserScriptsTable';
import {BrowserScriptsOperationsTable} from './BrowserScriptsOperationsTable';
import {snackActions} from '../../utilities/Snackbar';
import LinearProgress from '@material-ui/core/LinearProgress';
import {muiTheme} from '../../../themes/Themes';


const GET_BrowserScripts = gql`
query GetBrowserScripts($operator_id: Int!) {
  browserscript(where: {operator_id: {_eq: $operator_id}}) {
    active
    author
    user_modified
    script
    payloadtype {
      ptype
    }
    name
    id
    creation_time
    container_version_author
    container_version
    command {
      cmd
    }
  }
}
 `;
const SUB_BrowserScripts = gql`
subscription SubscribeBrowserScripts($operator_id: Int!) {
  browserscript(where: {operator_id: {_eq: $operator_id}}) {
    active
    author
    user_modified
    script
    payloadtype {
      ptype
    }
    name
    id
    creation_time
    container_version_author
    container_version
    command {
      cmd
    }
  }
}
 `;
 const GET_OperationBrowserScripts = gql`
query GetOperationBrowserScripts($operation_id: Int!) {
  browserscriptoperation(where: {operation_id: {_eq: $operation_id}}) {
    browserscript{
        active
        author
        user_modified
        script
        payloadtype {
          ptype
        }
        name
        id
        creation_time
        container_version_author
        container_version
        command {
          cmd
        }
      }
   operation{
    admin{
        username
    }
   }
  }
}
 `;
const SUB_OperationBrowserScripts = gql`
subscription SubscribeOperationBrowserScripts($operation_id: Int!) {
  browserscriptoperation(where: {operation_id: {_eq: $operation_id}}) {
    browserscript{
        active
        author
        user_modified
        script
        payloadtype {
          ptype
        }
        name
        id
        creation_time
        container_version_author
        container_version
        command {
          cmd
        }
      }
   operation{
    admin{
        username
    }
   }
  }
}
 `;
const updateBrowserScriptActive = gql`
mutation updateBrowserScriptActive($browserscript_id: Int!, $active: Boolean!) {
  update_browserscript_by_pk(pk_columns: {id: $browserscript_id}, _set: {active: $active}) {
    id
  }
}
`;
const updateBrowserScriptScript = gql`
mutation updateBrowserScriptScript($browserscript_id: Int!, $script: String!) {
  update_browserscript_by_pk(pk_columns: {id: $browserscript_id}, _set: {script: $script, user_modified: true}) {
    id
  }
}
`;
const updateBrowserScriptRevert = gql`
mutation updateBrowserScriptRevert($browserscript_id: Int!, $script: String!) {
  update_browserscript_by_pk(pk_columns: {id: $browserscript_id}, _set: {script: $script, user_modified: false}) {
    id
  }
}
`;

export function BrowserScripts(props){
    const me = useReactiveVar(meState);
    const { loading, error, data, subscribeToMore } = useQuery(GET_BrowserScripts, {variables: {operator_id: me.user.id}});
    const [getOperationScripts, {subscribeToMore: subscribeToMoreOperation, data: dataOperations, loading: loadingOperations}] = useLazyQuery(GET_OperationBrowserScripts);
    const [toggleActive] = useMutation(updateBrowserScriptActive, {
        onCompleted: data => {
            snackActions.success("Successfully Updated!", {autoHideDuration: 1000});
        },
        onError: data => {
            console.error(data);
        }
    });
    const [updateScript] = useMutation(updateBrowserScriptScript, {
        onCompleted: data => {
            snackActions.success("Successfully Updated!", {autoHideDuration: 1000});
        },
        onError: data => {
            console.error(data);
        }
    });
    const [revertScript] = useMutation(updateBrowserScriptRevert, {
        onCompleted: data => {
            snackActions.success("Successfully Updated!", {autoHideDuration: 1000});
        },
        onError: data => {
            console.error(data);
        }
    });
    useEffect( () => {
        getOperationScripts({variables: {operation_id: me.user.current_operation_id}});
    }, []);
    if (loading || loadingOperations) {
     return <LinearProgress style={{marginTop: "20px" }}/>;
    }
    if (error) {
     console.error(error);
     snackActions.error("Failed to get browser script data");
     return null;
    }
    const onToggleActive = ({browserscript_id, active}) => {
        toggleActive({variables: {browserscript_id, active}});
    }
    const onSubmitEdit = ({browserscript_id, script}) => {
        updateScript({variables: {browserscript_id, script}});
    }
    const onRevert = ({browserscript_id, script}) => {
        revertScript({variables:{browserscript_id, script}});
    }
    const onToggleOperation = ({browserscript_id}) => {
    
    }
    return (
    <React.Fragment>
        <BrowserScriptsTable {...data} onToggleActive={onToggleActive} onSubmitEdit={onSubmitEdit} onRevert={onRevert} onToggleOperation={onToggleOperation} subscribeToMoreMessages={() => subscribeToMore({
            document: SUB_BrowserScripts,
            variables: {operator_id: me.user.id},
            shouldResubscribe: true,
            updateQuery: (prev, {subscriptionData} ) => {
                console.log("in subscription", subscriptionData);
            }
        })}
        />
        {dataOperations && (
        <BrowserScriptsOperationsTable {...dataOperations} subscribeToMoreMessages={() => subscribeToMoreOperation({
            document: SUB_OperationBrowserScripts,
            variables: {operation_id: me.user.current_operation_id},
            shouldResubscribe: true,
            updateQuery: (prev, {subscriptionData} ) => {
                console.log("in subscription for operation", subscriptionData);
            }
        })}
        />)}
    </React.Fragment>
    );
}
