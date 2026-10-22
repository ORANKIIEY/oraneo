import {Component,type ReactNode} from 'react';
import {AlertTriangle,RefreshCw} from 'lucide-react';
interface Props{children:ReactNode}
interface State{broken:boolean}
export class ErrorBoundary extends Component<Props,State>{
 state:State={broken:false};
 static getDerivedStateFromError():State{return {broken:true}}
 componentDidCatch(error:Error){console.error('ORANEO view error',error)}
 render(){return this.state.broken?<section className="panel" role="alert"><AlertTriangle color="#b65c4c" size={30}/><h2>Unable to display this page</h2><p>Something unexpected occurred while rendering this view. Your saved warehouse data was not changed.</p><button className="btn primary" onClick={()=>this.setState({broken:false})}><RefreshCw size={16}/> Try again</button></section>:this.props.children}
}
