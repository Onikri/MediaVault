import * as Switch from '@radix-ui/react-switch';
import './ui-controls.css';
export default function UiSwitch({checked,defaultChecked,onChange,onCheckedChange,className='',type,...props}){
 return <Switch.Root {...props} checked={checked} defaultChecked={defaultChecked} className={'mv-switch '+className} onCheckedChange={value=>{onCheckedChange?.(value);onChange?.({target:{checked:value},currentTarget:{checked:value}});}}><Switch.Thumb className="mv-switch-thumb"/></Switch.Root>;
}
