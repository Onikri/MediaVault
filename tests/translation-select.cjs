// Reader translation settings use the Radix-based UiSelect: each select is a
// combobox button whose visible text is the chosen option, and the options live
// in a portal listbox. Values are not exposed in the DOM, so these helpers read
// and choose by the option text a person sees.
const combobox=(page,label)=>page.getByRole('combobox',{name:label,exact:true});

exports.selectedOption=async(page,label)=>(await combobox(page,label).innerText()).trim();

exports.chooseOption=async(page,label,option)=>{
 const trigger=combobox(page,label);
 await trigger.click();
 await page.getByRole('option',{name:option,exact:true}).click();
 await page.getByRole('listbox').waitFor({state:'detached'});
 await page.waitForFunction(([name,text])=>[...document.querySelectorAll('[role="combobox"]')].some(node=>node.getAttribute('aria-label')===name&&node.textContent.trim()===text),[label,option]);
};
