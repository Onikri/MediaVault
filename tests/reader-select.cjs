// The reader's translation settings and chapter jump use the Radix-based UiSelect:
// a combobox button showing the chosen option's text, with options in a portal
// listbox. Option values never reach the DOM, so these helpers read and choose by
// the text a reader sees.
const combobox=(page,label)=>page.getByRole('combobox',{name:label,exact:true});

exports.selectedOption=async(page,label)=>(await combobox(page,label).innerText()).trim();

exports.chooseOption=async(page,label,option)=>{
 await combobox(page,label).click();
 await page.getByRole('option',{name:option,exact:true}).click();
 await page.getByRole('listbox').waitFor({state:'detached'});
 await page.waitForFunction(([name,text])=>[...document.querySelectorAll('[role="combobox"]')].some(node=>node.getAttribute('aria-label')===name&&node.textContent.trim()===text),[label,option]);
};
