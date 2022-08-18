# encoding: utf-8

# This file is part of py-serializable
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) Paul Horton. All Rights Reserved.
import enum
import functools
import inspect
import json
from io import StringIO, TextIOWrapper
from abc import ABC, abstractmethod
from copy import copy
from json import JSONEncoder
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, Callable, TypeVar, cast, Iterable
from xml.etree import ElementTree

from .formatters import CurrentFormatter

AnySerializable = Union[
    Type["SimpleSerializable"], Type["SerializableObject"], Type["JsonSerializableObject"], Any
]


@enum.unique
class XmlArraySerializationType(enum.Enum):
    """
    Enum to differentiate how array-type properties (think Iterables) are serialized.

    Given a ``Warehouse`` has a property ``boxes`` that returns `List[Box]`:

    ``FLAT`` would allow for XML looking like:

    ``
    <warehouse>
        <box>..box 1..</box>
        <box>..box 2..</box>
    </warehouse>
    ``

    ``NESTED`` would allow for XML looking like:

    ``
    <warehouse>
        <boxes>
            <box>..box 1..</box>
            <box>..box 2..</box>
        </boxes>
    </warehouse>
    ``
    """
    FLAT = 1
    NESTED = 2


class SimpleSerializable(ABC):
    """
    You can create your own class (or use one of the provided classes in `serializable.helpers` to handle
    serializable and deserialization to Python primitive data types - e.g. datetime.

    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @classmethod
    @abstractmethod
    def serialize(cls, o: object) -> str:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize(cls, o: str) -> object:
        raise NotImplementedError


class SerializableObject(ABC):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @classmethod
    def get_array_property_configuration(cls) -> Dict[str, Tuple[XmlArraySerializationType, str, Any]]:
        """
        For properties that are arrays (think List or Set), this configuration can be used to affect how these
        properties are (de-)serialized.

        Return:
             `Dict[str, Tuple[XmlArraySerializationType, str, Type]]`
        """
        return {}

    @staticmethod
    def get_property_data_class_mappings() -> Dict[str, AnySerializable]:
        """
        This method should return a mapping from Python property name to either the Class that it deserializes to OR
        a Callable that handles the data for this property as part of deserialization.

        For example:
        ``
        {
            "chapters": Chapter
        }
        ``
        would allow for an Array of Chapters to be deserialized to a Set of `Chapter` objects.

        Returns:
            `Dict[str, AnySerializable]`
        """
        return {}

    @staticmethod
    def get_property_key_mappings() -> Dict[str, str]:
        """
        This method should return a `Dict[str, str]` that maps JSON property or key names to Python object property
        names.

        For example, in Python 'id' is a keyword and best practice is to suffix your property name with an underscore.
        Thus, your Python class might have a property named `id_` which when represented in JSON or XML should be 'id'.

        Therefor this method should return:
        ``
        {
           "id": "id_"
        }
        ``

        Returns:
            `Dict[str, str]`
        """
        return {}


class JsonSerializableObject(SerializableObject):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @staticmethod
    def get_json_key_removals() -> List[str]:
        """


        Returns:
            `List[str]`
        """
        return []

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> object:
        _data = copy(data)
        for k, v in data.items():
            if k in cls.get_json_key_removals():
                del (_data[k])
            else:
                decoded_k = CurrentFormatter.formatter.decode(property_name=k)
                if decoded_k in cls.get_property_key_mappings().values():
                    del (_data[k])
                    mapped_k = list(cls.get_property_key_mappings().keys())[
                        list(cls.get_property_key_mappings().values()).index(decoded_k)]
                    if mapped_k == '.':
                        mapped_k = decoded_k
                    _data[mapped_k] = v
                else:
                    del (_data[k])
                    _data[decoded_k] = v

        for k, v in _data.items():
            if k in cls.get_property_data_class_mappings():
                klass: AnySerializable = cls.get_property_data_class_mappings()[k]
                if isinstance(v, (list, set)):
                    items = []
                    for j in v:
                        if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                            items.append(klass.from_json(data=j))
                        elif inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                            items.append(klass.deserialize(j))
                        else:
                            # Enums treated this way too
                            items.append(klass(j))
                    _data[k] = items
                else:
                    if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                        _data[k] = klass.from_json(data=v)
                    elif inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                        _data[k] = klass.deserialize(v)
                    else:
                        _data[k] = klass(v)

            elif k in cls.get_array_property_configuration():
                serialization_type, sub_element_name, klass = cls.get_array_property_configuration()[k]
                if isinstance(v, (list, set)):
                    items = []
                    for j in v:
                        if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                            items.append(klass.from_json(data=j))
                        else:
                            items.append(klass(j))
                    _data[k] = items

        return cls(**_data)


class XmlSerializableObject(SerializableObject):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @classmethod
    def properties_as_attributes(cls) -> Set[str]:
        """
        A set of Property names that should be attributes on this class object when (de-)serialized as XML.

        Returns:
            `Set[str]`
        """
        return set()

    def as_xml(self, as_string: bool = True, element_name: Optional[str] = None) -> Union[ElementTree.Element, str]:
        this_e_attributes = {}
        for k, v in self.__dict__.items():
            # Remove leading _ in key names
            new_key = k[1:]
            if new_key.startswith('_') or '__' in new_key:
                continue

            if new_key in self.properties_as_attributes():
                if new_key in self.get_property_key_mappings():
                    new_key = self.get_property_key_mappings()[new_key]
                if CurrentFormatter.formatter:
                    new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                this_e_attributes.update({new_key: str(v)})

        this_e = ElementTree.Element(
            element_name or CurrentFormatter.formatter.encode(self.__class__.__name__), this_e_attributes
        )

        for k, v in self.__dict__.items():
            # Ignore None values by default
            if v is None:
                continue

            # Remove leading _ in key names
            new_key = k[1:]
            if new_key.startswith('_') or '__' in new_key:
                continue

            if new_key not in self.properties_as_attributes():
                if new_key in self.get_property_key_mappings():
                    new_key = self.get_property_key_mappings()[new_key]
                    if new_key == '.':
                        this_e.text = str(v)
                        continue

                if new_key in self.get_property_data_class_mappings():
                    klass_ss = self.get_property_data_class_mappings()[new_key]
                    if CurrentFormatter.formatter:
                        new_key = CurrentFormatter.formatter.encode(property_name=new_key)
                    if callable(getattr(klass_ss, "as_xml", None)):
                        this_e.append(v.as_xml(as_string=False, element_name=new_key))
                    elif inspect.isclass(klass_ss) and callable(getattr(klass_ss, "serialize", None)):
                        ElementTree.SubElement(this_e, new_key).text = str(klass_ss.serialize(v))
                elif isinstance(v, (list, set)):
                    if new_key in self.get_array_property_configuration():
                        (array_type, nested_key, klass) = self.get_array_property_configuration()[new_key]
                    else:
                        (array_type, nested_key) = (XmlArraySerializationType.FLAT, new_key)

                    if CurrentFormatter.formatter:
                        new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                    if array_type == XmlArraySerializationType.NESTED:
                        nested_e = ElementTree.SubElement(this_e, new_key)
                        item_key = new_key
                    else:
                        nested_e = this_e
                        item_key = nested_key

                    for j in v:
                        if callable(getattr(j, "as_xml", None)):
                            nested_e.append(j.as_xml(as_string=False))
                        else:
                            ElementTree.SubElement(nested_e, item_key).text = str(j)

                    # if array_config
                else:
                    if CurrentFormatter.formatter:
                        new_key = CurrentFormatter.formatter.encode(property_name=new_key)
                    if isinstance(v, enum.Enum):
                        ElementTree.SubElement(this_e, new_key).text = str(v.value)
                    else:
                        ElementTree.SubElement(this_e, new_key).text = str(v)

        if as_string:
            return ElementTree.tostring(this_e, 'unicode')
        else:
            return this_e

    @classmethod
    def from_xml(cls, data: Union[TextIOWrapper, ElementTree.Element],
                 default_namespace: Optional[str] = None) -> object:

        if isinstance(data, TextIOWrapper):
            data = ElementTree.fromstring(data.read())

        if default_namespace is None:
            _namespaces = dict(
                [node for _, node in
                 ElementTree.iterparse(StringIO(ElementTree.tostring(data, 'unicode')), events=['start-ns'])]
            )
            if 'ns0' in _namespaces:
                default_namespace = _namespaces['ns0']
            else:
                default_namespace = ''
        _data: Dict[str, Any] = {}

        # Handle any attributes first
        for attribute_name, attribute_value in data.attrib.items():
            decoded_name = CurrentFormatter.formatter.decode(property_name=attribute_name)
            if decoded_name in cls.get_property_key_mappings().values():
                decoded_name = list(cls.get_property_key_mappings().keys())[
                    list(cls.get_property_key_mappings().values()).index(decoded_name)]
            if decoded_name in cls.properties_as_attributes():
                if decoded_name in cls.get_property_data_class_mappings():
                    klass = cls.get_property_data_class_mappings()[decoded_name]

                    if inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                        _data.update({
                            decoded_name: klass.deserialize(str(attribute_value))
                        })
                    else:
                        _data.update({
                            decoded_name: klass(str(attribute_value))
                        })
                else:
                    _data[decoded_name] = int(str(attribute_value)) if str(
                        attribute_value).isdigit() else attribute_value

        # Handle Node text content
        if data.text and '.' in cls.get_property_key_mappings().values():
            decoded_name = list(cls.get_property_key_mappings().keys())[
                list(cls.get_property_key_mappings().values()).index('.')]
            _data[decoded_name] = str(data.text).strip()

        # Handle child elements
        for child_e in data:
            child_e_tag_name = str(child_e.tag).replace('{' + default_namespace + '}', '')
            decoded_name = CurrentFormatter.formatter.decode(property_name=child_e_tag_name)
            array_config = [{k: v} for k, v in cls.get_array_property_configuration().items() if
                            str(child_e_tag_name) in v]

            if decoded_name in cls.get_property_key_mappings().values():
                decoded_name = list(cls.get_property_key_mappings().keys())[
                    list(cls.get_property_key_mappings().values()).index(decoded_name)]

            if decoded_name in cls.get_array_property_configuration():
                # Handle Nested Lists
                array_type, nested_tag, klass = cls.get_array_property_configuration()[decoded_name]
                if not array_type == XmlArraySerializationType.NESTED:
                    raise ValueError('Only NESTED expected here!')

                _data.update({
                    decoded_name: []
                })

                for sub_child_e in child_e:
                    sub_child_e_tag_name = str(sub_child_e.tag).replace('{' + default_namespace + '}', '')
                    if sub_child_e_tag_name != nested_tag:
                        raise ValueError(f'Only {nested_tag} elements expected under {child_e_tag_name}')
                    _data[decoded_name].append(klass.from_xml(data=sub_child_e, default_namespace=default_namespace))

            elif array_config:
                prop_name, (array_type, tag_name, klass) = next(iter(array_config[0].items()))
                if not array_type == XmlArraySerializationType.FLAT:
                    raise ValueError('Only FLAT expected here!')
                if prop_name not in _data:
                    _data.update({
                        prop_name: []
                    })
                if callable(getattr(klass, "from_xml", None)):
                    _data[prop_name].append(klass.from_xml(data=child_e))
                else:
                    _data[prop_name].append(klass(child_e.text))

            elif decoded_name in cls.get_property_data_class_mappings():
                klass = cls.get_property_data_class_mappings()[decoded_name]

                if inspect.isclass(klass) and callable(getattr(klass, "from_xml", None)):
                    _data.update({
                        decoded_name: klass.from_xml(data=child_e)
                    })
                elif inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                    _data.update({
                        decoded_name: klass.deserialize(str(child_e.text))
                    })
                else:
                    _data.update({
                        decoded_name: klass(str(child_e.text))
                    })
            elif decoded_name in cls.__dict__:
                _data.update({
                    decoded_name: int(str(child_e.text)) if str(child_e.text).isdigit() else child_e.text
                })

            else:
                raise ValueError(f'Element "{child_e_tag_name}" does not map to a Property of Class {cls.__name__}')

        return cls(**_data)


class DefaultJsonEncoder(JSONEncoder):

    def default(self, o: Any) -> Any:
        print(f'Serializing {o} to JSON...')

        # Enum
        if isinstance(o, enum.Enum):
            return o.value

        # Iterables
        if isinstance(o, (list, set)):
            return list(o)

        # Classes
        if isinstance(o, object):
            d: Dict[Any, Any] = {}
            klass_qualified_name = f'{o.__module__}.{o.__class__.__qualname__}'
            print(f'Class: {o}: {klass_qualified_name}')
            serializable_property_info = ObjectMetadataLibrary.klass_property_mappings.get(klass_qualified_name, {})
            print(f'   Prop Info: {serializable_property_info}')

            for k, v in o.__dict__.items():
                # Exclude None values by default
                if v is None:
                    continue

                # Remove leading _ in key names
                new_key = k[1:]
                if new_key.startswith('_') or '__' in new_key:
                    continue

                if new_key in serializable_property_info:
                    prop_info = serializable_property_info.get(new_key)
                    print(f'   {new_key} has Prop Info: {prop_info}')

                    if prop_info.custom_name(serialization_type=SerializationType.JSON):
                        new_key = prop_info.custom_name(serialization_type=SerializationType.JSON)

                    if CurrentFormatter.formatter:
                        new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                    if prop_info.custom_type:
                        if inspect.isclass(prop_info.custom_type) and callable(
                                getattr(prop_info.custom_type, "serialize", None)):
                            v = prop_info.custom_type.serialize(v)
                        else:
                            v = prop_info.custom_type(v)

                # print(f'   Serializing {k} for {v.__class__.__name__} to JSON')
                # if ObjectMetadataLibrary.is_klass_serializable(f'{v.__module__}.{v.__class__}'):
                #     print(f'   {v} is a serializable class')
                #
                # print(f'{ObjectMetadataLibrary.klass_property_mappings[o.__class__.__name__].get(new_key)}')
                # if ObjectMetadataLibrary.klass_property_mappings[o.__class__.__name__].get()

                # if isinstance(o, SerializableObject):
                #     if new_key in o.get_property_key_mappings():
                #         new_key_candidate = o.get_property_key_mappings()[new_key]
                #         if new_key_candidate != '.':
                #             new_key = new_key_candidate
                #
                #     if new_key in o.get_property_data_class_mappings():
                #         klass = o.get_property_data_class_mappings()[new_key]
                #
                #         if inspect.isclass(klass) and callable(getattr(klass, "serialize", None)):
                #             v = klass.serialize(v)

                if CurrentFormatter.formatter:
                    new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                d.update({new_key: v})

            return d

        # Fallback to default
        super().default(o=o)


@enum.unique
class SerializationType(str, enum.Enum):
    JSON = 'JSON'
    XML = 'XML'


_DEFAULT_SERIALIZATION_TYPES = [SerializationType.JSON, SerializationType.XML]


def _as_json(self):
    print(f'Dumping {self} to JSON...')
    return json.dumps(self, cls=DefaultJsonEncoder)


def _from_json(cls, data: Dict[str, Any]) -> object:
    print(f'Rendering JSON to {cls}...')
    _data = copy(data)
    for k, v in data.items():
        if k in cls.get_json_key_removals():
            del (_data[k])
        else:
            decoded_k = CurrentFormatter.formatter.decode(property_name=k)
            if decoded_k in cls.get_property_key_mappings().values():
                del (_data[k])
                mapped_k = list(cls.get_property_key_mappings().keys())[
                    list(cls.get_property_key_mappings().values()).index(decoded_k)]
                if mapped_k == '.':
                    mapped_k = decoded_k
                _data[mapped_k] = v
            else:
                del (_data[k])
                _data[decoded_k] = v

    for k, v in _data.items():
        if k in cls.get_property_data_class_mappings():
            klass: AnySerializable = cls.get_property_data_class_mappings()[k]
            if isinstance(v, (list, set)):
                items = []
                for j in v:
                    if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                        items.append(klass.from_json(data=j))
                    elif inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                        items.append(klass.deserialize(j))
                    else:
                        # Enums treated this way too
                        items.append(klass(j))
                _data[k] = items
            else:
                if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                    _data[k] = klass.from_json(data=v)
                elif inspect.isclass(klass) and callable(getattr(klass, "deserialize", None)):
                    _data[k] = klass.deserialize(v)
                else:
                    _data[k] = klass(v)

        elif k in cls.get_array_property_configuration():
            serialization_type, sub_element_name, klass = cls.get_array_property_configuration()[k]
            if isinstance(v, (list, set)):
                items = []
                for j in v:
                    if inspect.isclass(klass) and callable(getattr(klass, "from_json", None)):
                        items.append(klass.from_json(data=j))
                    else:
                        items.append(klass(j))
                _data[k] = items

    return cls(**_data)


def _as_xml(self, as_string: bool = True, element_name: Optional[str] = None) -> Union[ElementTree.Element, str]:
    print(f'Dumping {self} to XML...')

    this_e_attributes = {}
    klass_qualified_name = f'{self.__module__}.{self.__class__.__qualname__}'
    serializable_property_info = ObjectMetadataLibrary.klass_property_mappings.get(klass_qualified_name, {})

    # Handle any Properties that should be attributes
    for k, v in self.__dict__.items():
        # Remove leading _ in key names
        new_key = k[1:]
        if new_key.startswith('_') or '__' in new_key:
            continue

        if new_key in serializable_property_info:
            prop_info = serializable_property_info.get(new_key)
            if prop_info and prop_info.is_xml_attribute:
                new_key = prop_info.custom_names.get(SerializationType.XML, new_key)
                if CurrentFormatter.formatter:
                    new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                this_e_attributes.update({new_key: str(v)})

    this_e = ElementTree.Element(
        element_name or CurrentFormatter.formatter.encode(self.__class__.__name__), this_e_attributes
    )

    # Handle remaining Properties that will be sub elements
    for k, v in self.__dict__.items():
        # Ignore None values by default
        if v is None:
            continue

        # Remove leading _ in key names
        new_key = k[1:]
        if new_key.startswith('_') or '__' in new_key:
            continue

        if new_key in serializable_property_info:
            prop_info = serializable_property_info.get(new_key)

            if not prop_info.is_xml_attribute:
                print(f'   {new_key} has Prop Info: {prop_info}')

                new_key = prop_info.custom_names.get(SerializationType.XML, new_key)

                if new_key == '.':
                    this_e.text = str(v)
                    continue

                if CurrentFormatter.formatter:
                    new_key = CurrentFormatter.formatter.encode(property_name=new_key)

                if prop_info.custom_type:
                    print(f'{new_key} has custom type: {prop_info.custom_type}')
                    ElementTree.SubElement(this_e, new_key).text = str(prop_info.custom_type.serialize(v))

                    # klass_ss = self.get_property_data_class_mappings()[new_key]
                    # if CurrentFormatter.formatter:
                    #     new_key = CurrentFormatter.formatter.encode(property_name=new_key)
                    # if callable(getattr(klass_ss, "as_xml", None)):
                    #     this_e.append(v.as_xml(as_string=False, element_name=new_key))
                    # elif inspect.isclass(klass_ss) and callable(getattr(klass_ss, "serialize", None)):
                    #     ElementTree.SubElement(this_e, new_key).text = str(klass_ss.serialize(v))
                elif prop_info.is_array():
                    print(f'{new_key} is Array')
                    print(f'    {prop_info.xml_array_config}')

                    _array_type, nested_key = prop_info.xml_array_config

                    if _array_type == XmlArraySerializationType.NESTED:
                        nested_e = ElementTree.SubElement(this_e, new_key)
                    else:
                        nested_e = this_e

                    print(f'   Array Item Type: {prop_info.type_}')

                    for j in v:
                        if not prop_info.is_primitive_type():
                            print(f'  {k}/{new_key}: {prop_info}')
                            nested_e.append(j.as_xml(as_string=False, element_name=nested_key))
                        elif prop_info.concrete_type() in (float, int):
                            ElementTree.SubElement(nested_e, nested_key).text = str(j)
                        elif prop_info.concrete_type() is bool:
                            ElementTree.SubElement(nested_e, nested_key).text = str(j).lower()
                        else:
                            # Assume type is str
                            ElementTree.SubElement(nested_e, nested_key).text = str(j)
                elif prop_info.is_enum():
                    print(f'Serializing Enum: {new_key}')
                    ElementTree.SubElement(this_e, new_key).text = str(v.value)
                elif prop_info.type_ and not prop_info.is_primitive_type():
                    # Handle properties that have a type that is not a Python Primitive (e.g. int, float, str)
                    print(f'{new_key} has type: {prop_info.type_}')
                    this_e.append(v.as_xml(as_string=False, element_name=new_key))
                elif prop_info.type_ in (float, int):
                    ElementTree.SubElement(this_e, new_key).text = str(v)
                elif prop_info.type_ is bool:
                    ElementTree.SubElement(this_e, new_key).text = str(v).lower()
                else:
                    # Assume type is str
                    ElementTree.SubElement(this_e, new_key).text = str(v)

    if as_string:
        return ElementTree.tostring(this_e, 'unicode')
    else:
        return this_e


class ObjectMetadataLibrary:
    _klass_property_array_config: Dict[str, Tuple[SerializationType, str]] = {}
    _klass_property_attributes: Set[str] = set()
    _klass_property_names: Dict[str, Dict[SerializationType, str]] = {}
    _klass_property_types: Dict[str, Type] = {}
    klass_mappings: Dict[str, 'ObjectMetadataLibrary.SerializableClass'] = {}
    klass_property_mappings: Dict[str, Dict[str, 'ObjectMetadataLibrary.SerializableProperty']] = {}

    class SerializableClass:

        def __init__(self, *, klass: Any, custom_name: Optional[str] = None,
                     serialization_types: Optional[Iterable[SerializationType]] = None) -> None:
            self._name = klass.__name__
            self._custom_name = custom_name
            if serialization_types is None:
                serialization_types = _DEFAULT_SERIALIZATION_TYPES
            self._serialization_types = serialization_types

        @property
        def name(self) -> str:
            return self._name

        @property
        def custom_name(self) -> Optional[str]:
            return self._custom_name

        @property
        def serialization_types(self) -> Iterable[SerializationType]:
            return self._serialization_types

        def __repr__(self) -> str:
            return f'<s.oml.SerializableClass name={self.name}>'

    class SerializableProperty:

        _ARRAY_TYPES = ('List', 'Set')
        _PRIMITIVE_TYPES = (bool, int, float, str)

        def __init__(self, *, prop_name: str, prop_type: Any, custom_names: Dict[SerializationType, str],
                     custom_type: Optional[Any] = None, is_xml_attribute: bool = False,
                     xml_array_config: Optional[Tuple[XmlArraySerializationType, str]] = None) -> None:
            self._name = prop_name
            self._custom_names = custom_names
            self._type_ = prop_type
            self._custom_type = custom_type
            self._is_xml_attribute = is_xml_attribute
            self._xml_array_config = xml_array_config

        @property
        def name(self) -> str:
            return self._name

        @property
        def custom_names(self) -> Dict[SerializationType, str]:
            return self._custom_names

        def custom_name(self, serialization_type: SerializationType.JSON) -> Optional[str]:
            return self.custom_names.get(serialization_type, None)

        @property
        def type_(self) -> Any:
            return self._type_

        def concrete_type(self) -> Any:
            if self.is_optional():
                t, n = self.type_.__args__
                if t.__name__ in self._ARRAY_TYPES:
                    t, = t.__args__
                return t
            else:
                if self.type_.__name__ in self._ARRAY_TYPES:
                    t, = self.type_.__args__
                    return t
                return self.type_

        @property
        def custom_type(self) -> Optional[Any]:
            return self._custom_type

        @property
        def is_xml_attribute(self) -> bool:
            return self._is_xml_attribute

        @property
        def xml_array_config(self) -> Optional[Tuple[XmlArraySerializationType, str]]:
            return self._xml_array_config

        def is_array(self) -> bool:
            if self.is_optional():
                t, n = self.type_.__args__
                if t.__name__ in self._ARRAY_TYPES:
                    return True
            elif self.type_.__name__ in self._ARRAY_TYPES:
                return True

            return False

        def is_optional(self) -> bool:
            return self.type_.__name__ == 'Optional'

        def is_enum(self) -> bool:
            return issubclass(type(self.concrete_type()), enum.EnumMeta)

        def is_primitive_type(self) -> bool:
            return self.concrete_type() in self._PRIMITIVE_TYPES

        def __repr__(self) -> str:
            return f'<s.oml.SerializableProperty name={self.name}, custom_names={self.custom_names}, type={self.type_}, ' \
                   f'custom_type={self.custom_type}, xml_attr={self.is_xml_attribute}>'

    @classmethod
    def is_klass_serializable(cls, klass) -> bool:
        # print(f'Is {klass.__module__}.{klass.__name__} serializable?')
        if type(klass) is Type:
            return f'{klass.__module__}.{klass.__name__}' in cls.klass_mappings
        return klass in cls.klass_mappings

    @classmethod
    def is_property(cls, o: object) -> bool:
        return isinstance(o, property)

    @classmethod
    def register_klass(cls, klass, a, serialization_types: Iterable[SerializationType]) -> None:
        print(f'register_klass(): {klass}, {a}')
        if cls.is_klass_serializable(klass=klass):
            return klass

        cls.klass_mappings.update({
            f'{klass.__module__}.{klass.__qualname__}': ObjectMetadataLibrary.SerializableClass(
                klass=klass, serialization_types=serialization_types
            )
        })

        qualified_class_name = f'{klass.__module__}.{klass.__qualname__}'
        cls.klass_property_mappings.update({qualified_class_name: {}})
        print(f'Registering {qualified_class_name} --- {a}')
        for name, o in inspect.getmembers(klass, ObjectMetadataLibrary.is_property):
            qualified_property_name = f'{qualified_class_name}.{name}'
            # print(f'   Property: {name}: {o.fget}')
            prop_arg_specs = inspect.getfullargspec(o.fget)
            # print(f'   {prop_arg_specs}')

            cls.klass_property_mappings[qualified_class_name].update({
                name: ObjectMetadataLibrary.SerializableProperty(
                    prop_name=name,
                    custom_names=ObjectMetadataLibrary._klass_property_names.get(qualified_property_name, {}),
                    prop_type=prop_arg_specs.annotations.get('return', None),
                    custom_type=ObjectMetadataLibrary._klass_property_types.get(qualified_property_name, None),
                    is_xml_attribute=(qualified_property_name in ObjectMetadataLibrary._klass_property_attributes),
                    xml_array_config=ObjectMetadataLibrary._klass_property_array_config.get(
                        qualified_property_name, None
                    )
                )
            })
        print('')

        if SerializationType.JSON in serialization_types:
            setattr(klass, 'as_json', _as_json)
            setattr(klass, 'from_json', _from_json)

        if SerializationType.XML in serialization_types:
            setattr(klass, 'as_xml', _as_xml)
            # setattr(klass, 'from_json', _from_json)

        return klass

    @classmethod
    def register_custom_json_property_name(cls, qual_name: str, json_property_name: str) -> None:
        print(f'Registering custom JSON property name for {qual_name} as {json_property_name}')
        if qual_name in cls._klass_property_names:
            cls._klass_property_names[qual_name].update({SerializationType.JSON: json_property_name})
        else:
            cls._klass_property_names.update({qual_name: {SerializationType.JSON: json_property_name}})
        print(f'    Now {cls._klass_property_names.get(qual_name)}')

    @classmethod
    def register_custom_xml_property_name(cls, qual_name: str, xml_property_name: str) -> None:
        print(f'Registering custom XML property name for {qual_name} as {xml_property_name}')
        if qual_name in cls._klass_property_names:
            cls._klass_property_names[qual_name].update({SerializationType.XML: xml_property_name})
        else:
            cls._klass_property_names.update({qual_name: {SerializationType.XML: xml_property_name}})
        print(f'    Now {cls._klass_property_names.get(qual_name)}')

    @classmethod
    def register_xml_property_array_config(cls, qual_name: str,
                                           array_type: XmlArraySerializationType, child_name: str) -> None:
        print(f'Registering XML property Array Config for: {qual_name}')
        cls._klass_property_array_config.update({qual_name: (array_type, child_name)})

    @classmethod
    def register_xml_property_attribute(cls, qual_name: str) -> None:
        print(f'Registering XML property name for as attribute: {qual_name}')
        cls._klass_property_attributes.add(qual_name)

    @classmethod
    def register_property_type_mapping(cls, qual_name: str, mapped_type: Any) -> None:
        print(f'Registering type mapping for property name for {qual_name} as {mapped_type}')
        cls._klass_property_types.update({qual_name: mapped_type})


def serializable_class(cls=None, /, *, name=None, serialization_types: Optional[Iterable[SerializationType]] = None):
    if serialization_types is None:
        serialization_types = _DEFAULT_SERIALIZATION_TYPES

    def wrap(cls):
        return ObjectMetadataLibrary.register_klass(klass=cls, a=name, serialization_types=serialization_types)

    # See if we're being called as @register_klass or @register_klass().
    if cls is None:
        # We're called with parens.
        return wrap

    # We're called as @register_klass without parens.
    return wrap(cls)


T = TypeVar('T')


def type_mapping(type_: Any) -> Callable[[T], T]:
    def outer(f: T) -> T:
        print(f'*** REGISTERING TYPE MAPPING FOR {f.__module__}.{f.__qualname__} AS {type_}')
        ObjectMetadataLibrary.register_property_type_mapping(
            qual_name=f'{f.__module__}.{f.__qualname__}', mapped_type=type_
        )

        @functools.wraps(f)
        def inner(*args, **kwargs):
            return f(*args, **kwargs)

        return cast(T, inner)

    return outer


def json_name(name: str) -> Callable[[T], T]:
    def outer(f: T) -> T:
        print(f'*** REGISTERING ALTERNATIVE NAME FOR {f.__module__}.{f.__qualname__} AS {name}')
        ObjectMetadataLibrary.register_custom_json_property_name(
            qual_name=f'{f.__module__}.{f.__qualname__}', json_property_name=name
        )

        @functools.wraps(f)
        def inner(*args, **kwargs):
            return f(*args, **kwargs)

        return cast(T, inner)

    return outer


def xml_attribute() -> Callable[[T], T]:
    def outer(f: T) -> T:
        print(f'*** REGISTERING {f.__module__}.{f.__qualname__} AS XML ATTRIBUTE')
        ObjectMetadataLibrary.register_xml_property_attribute(qual_name=f'{f.__module__}.{f.__qualname__}')

        @functools.wraps(f)
        def inner(*args, **kwargs):
            return f(*args, **kwargs)

        return cast(T, inner)

    return outer


def xml_array(array_type: XmlArraySerializationType, child_name: str) -> Callable[[T], T]:
    def outer(f: T) -> T:
        print(f'*** REGISTERING XML ARRAY CONFIG FOR {f.__module__}.{f.__qualname__} AS {array_type}:{child_name}')
        ObjectMetadataLibrary.register_xml_property_array_config(
            qual_name=f'{f.__module__}.{f.__qualname__}', array_type=array_type, child_name=child_name
        )

        @functools.wraps(f)
        def inner(*args, **kwargs):
            return f(*args, **kwargs)

        return cast(T, inner)

    return outer


def xml_name(name: str) -> Callable[[T], T]:
    def outer(f: T) -> T:
        print(f'*** REGISTERING ALTERNATIVE NAME FOR {f.__module__}.{f.__qualname__} AS {name}')
        ObjectMetadataLibrary.register_custom_xml_property_name(
            qual_name=f'{f.__module__}.{f.__qualname__}', xml_property_name=name
        )

        @functools.wraps(f)
        def inner(*args, **kwargs):
            return f(*args, **kwargs)

        return cast(T, inner)

    return outer
