import {Component} from 'react';
import {useMediaVaultPlayer} from './player-session.js';
class ExtensionBoundary extends Component{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 componentDidCatch(error){this.props.onError?.(error);}
 render(){return this.state.failed?null:this.props.children;}
}
export default function PlayerExtensionSlot({name,extensions,onError}){
 const player=useMediaVaultPlayer();
 return <div className={'player-extension-slot player-extension-'+name} data-player-slot={name}>{(extensions||[]).filter(x=>x?.id&&x.slot===name&&x.Component).map(extension=>{
  const View=extension.Component;
  return <ExtensionBoundary key={extension.id} onError={onError}><View player={player}/></ExtensionBoundary>;
 })}</div>;
}
